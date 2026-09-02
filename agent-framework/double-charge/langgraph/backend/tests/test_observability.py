import logging
import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace

from model_to_harness_langgraph.observability import (
    configure_optional_azure_monitor,
    project_durable_node_spans,
    reset_observability_for_tests,
)
from opentelemetry import trace


def test_azure_monitor_suppresses_exporter_transport_logging(monkeypatch):
    calls: list[tuple[str, object]] = []
    package = ModuleType("azure.monitor.opentelemetry")
    package.configure_azure_monitor = lambda *, connection_string, resource: calls.append(
        (connection_string, resource)
    )
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", package)
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test")
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    reset_observability_for_tests()

    transport = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
    exporter = logging.getLogger("azure.monitor.opentelemetry.exporter")
    previous_levels = transport.level, exporter.level
    try:
        transport.setLevel(logging.INFO)
        exporter.setLevel(logging.INFO)

        assert configure_optional_azure_monitor() is True

        assert calls[0][0] == "InstrumentationKey=test"
        assert calls[0][1].attributes["service.name"] == "model-to-harness-langgraph"
        assert transport.level == logging.WARNING
        assert exporter.level == logging.WARNING
    finally:
        transport.setLevel(previous_levels[0])
        exporter.setLevel(previous_levels[1])


def test_hosted_runtime_reuses_agentserver_monitor_provider(monkeypatch):
    reset_observability_for_tests()
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.test/projects/demo")

    assert configure_optional_azure_monitor() is True


def test_durable_node_projection_uses_safe_audit_metadata(monkeypatch):
    captured: list[dict[str, object]] = []

    class FakeSpan:
        def end(self, *, end_time):
            captured[-1]["end_time"] = end_time

    class FakeTracer:
        def start_span(self, name, *, context, start_time, attributes):
            captured.append(
                {
                    "name": name,
                    "context": context,
                    "start_time": start_time,
                    "attributes": attributes,
                }
            )
            return FakeSpan()

    monkeypatch.setattr(trace, "get_tracer", lambda _name: FakeTracer())
    started = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    events = [
        SimpleNamespace(
            node="submit_refund",
            case_id="case-1",
            run_id="run-1",
            timestamp=started,
            summary="sensitive summary",
            data={"idempotency_key": "sensitive-key"},
        ),
        SimpleNamespace(
            node="submit_refund",
            case_id="case-1",
            run_id="run-1",
            timestamp=started + timedelta(seconds=1),
            summary="another sensitive summary",
            data={"refund_id": "sensitive-refund"},
        ),
    ]

    project_durable_node_spans(events, parent_context="parent")

    assert captured[0]["name"] == "workflow.node.submit_refund"
    assert captured[0]["context"] == "parent"
    assert captured[0]["attributes"] == {
        "workflow.node": "submit_refund",
        "workflow.case_id": "case-1",
        "workflow.run_id": "run-1",
        "workflow.event_count": 2,
        "workflow.trace_source": "durable_audit_projection",
    }
