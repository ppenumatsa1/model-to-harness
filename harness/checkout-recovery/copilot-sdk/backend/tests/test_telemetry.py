import json
import logging
from hashlib import sha256
from unittest.mock import Mock

import pytest
from checkout_recovery_copilot.infrastructure import telemetry
from checkout_recovery_copilot.infrastructure.telemetry import SafeExporter, operation
from opentelemetry import _logs
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import Link, SpanContext, SpanKind, Status, StatusCode, TraceState

SECRET = "private prompt plan tool-result credential raw-error"
CORRELATION = sha256(b"case-id").hexdigest()[:24]


class RecordingExporter(SpanExporter):
    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS


def test_exporter_redacts_every_content_surface_without_dropping_spans(monkeypatch):
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", f"secret={SECRET},service.name={SECRET}")
    context = SpanContext(123, 456, False, trace_state=TraceState([("secret", SECRET)]))
    parent = SpanContext(123, 455, True, trace_state=TraceState([("secret", SECRET)]))
    collector = RecordingExporter()
    exporter = SafeExporter(collector)
    result = exporter.export(
        [
            ReadableSpan(
                name="checkout.model",
                context=context,
                parent=parent,
                kind=SpanKind.CLIENT,
                start_time=100,
                end_time=200,
                attributes={
                    "checkout.component": "copilot",
                    "checkout.correlation": CORRELATION,
                    "gen_ai.input.messages": SECRET,
                    "gen_ai.tool.call.arguments": SECRET,
                    "gen_ai.tool.call.result": SECRET,
                    "db.connection_string": SECRET,
                    "error.type": SECRET,
                },
                resource=Resource({"service.name": SECRET, "secret": SECRET}),
                status=Status(StatusCode.ERROR, SECRET),
                events=[Event(SECRET, {"secret": SECRET})],
                links=[Link(context, {"secret": SECRET})],
                instrumentation_scope=InstrumentationScope(
                    SECRET, SECRET, SECRET, {"secret": SECRET}
                ),
            ),
            ReadableSpan(name=f"checkout.{SECRET}"),
            ReadableSpan(name=f"gen_ai.{SECRET}"),
        ]
    )
    assert result is SpanExportResult.SUCCESS
    assert len(collector.spans) == 3
    span = collector.spans[0]
    assert span.attributes == {"checkout.component": "copilot", "checkout.correlation": CORRELATION}
    assert (span.context.trace_id, span.context.span_id) == (123, 456)
    assert (span.parent.trace_id, span.parent.span_id, span.parent.is_remote) == (123, 455, True)
    assert not span.context.trace_state and not span.parent.trace_state
    assert span.kind is SpanKind.CLIENT
    assert (span.start_time, span.end_time) == (100, 200)
    assert span.status.status_code is StatusCode.ERROR
    assert [item.name for item in collector.spans] == [
        "checkout.model",
        "checkout.native.span",
        "checkout.native.span",
    ]
    for item in collector.spans:
        assert item.status.description is None
        assert item.events == ()
        assert item.links == ()
        assert item.instrumentation_scope is None
        assert item.resource.attributes == {"service.name": "checkout-recovery-copilot-api"}
        assert SECRET not in item.to_json()


@pytest.mark.parametrize("value", [SECRET, "a" * 25, "A" * 24, "", 42, True, [SECRET]])
def test_allowlisted_attribute_keys_do_not_allow_arbitrary_values(value):
    collector = RecordingExporter()
    SafeExporter(collector).export(
        [
            ReadableSpan(
                name="checkout.api",
                attributes={
                    "checkout.component": value,
                    "checkout.correlation": value,
                    "gen_ai.operation.name": value,
                },
            )
        ]
    )
    assert collector.spans[0].attributes == {}


def test_explicit_fixture_helper_keeps_only_known_synthetic_diagnostics(caplog):
    collector = RecordingExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SafeExporter(collector)))
    tracer = provider.get_tracer("fixture-test")
    with tracer.start_as_current_span("checkout.tool.read_payment") as span:
        telemetry.record_fixture_diagnostic(
            span, "read_payment", {"status": "captured", "amount_minor": 4250},
        )
    with tracer.start_as_current_span("checkout.tool.read_payment") as span:
        telemetry.record_fixture_diagnostic(
            span, "read_payment", {"status": "captured", "amount_minor": 4250, "secret": SECRET},
        )
    provider.shutdown()
    assert collector.spans[0].attributes["gen_ai.tool.call.arguments"] == "{}"
    assert collector.spans[0].attributes["gen_ai.tool.call.result"] == (
        '{"amount_minor":4250,"status":"captured"}'
    )
    assert collector.spans[1].attributes == {}
    assert "Omitted non-allowlisted diagnostic trace content" in caplog.text
    assert SECRET not in caplog.text


def test_fixture_marker_cannot_bypass_exporter_payload_validation():
    collector = RecordingExporter()
    SafeExporter(collector).export([
        ReadableSpan(name="checkout.tool.read_payment", attributes={
            "checkout.fixture_content": True,
            "gen_ai.tool.name": "read_payment",
            "gen_ai.tool.call.arguments": "{}",
            "gen_ai.tool.call.result": SECRET,
        }),
    ])
    assert collector.spans[0].attributes == {}


def test_local_receipt_provider_is_independent_of_azure_and_sanitized(monkeypatch, tmp_path):
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: None)
    path = tmp_path / "native.jsonl"
    provider = telemetry.configure_api_telemetry(connection_string=None, trace_file=path)
    tracer = provider.get_tracer("test.local")
    with tracer.start_as_current_span("checkout.tool.read_order") as span:
        span.set_attribute("gen_ai.input.messages", SECRET)
        telemetry.record_fixture_diagnostic(span, "read_order", {"status": "checkout_failed"})
    provider.force_flush()
    provider.shutdown()
    receipt = path.with_name(path.name + ".application.jsonl")
    assert receipt.stat().st_mode & 0o777 == 0o600
    row = json.loads(receipt.read_text())
    assert row["attributes"]["gen_ai.tool.call.result"] == '{"status":"checkout_failed"}'
    assert SECRET not in receipt.read_text()


@pytest.mark.parametrize("name", [
    "checkout.tool.write_plan", "checkout.tool.read_plan", "checkout.tool.delegate_inventory",
])
def test_workspace_and_delegation_handler_names_remain_readable(name):
    collector = RecordingExporter()
    SafeExporter(collector).export([ReadableSpan(name=name)])
    assert collector.spans[0].name == name


def test_application_receipt_write_failure_is_explicit(tmp_path, monkeypatch, caplog):
    from checkout_recovery_copilot.infrastructure import copilot_telemetry

    monkeypatch.setattr(copilot_telemetry, "MAX_RECEIPT_BYTES", 0)
    exporter = telemetry.LocalSpanExporter(tmp_path / "full.jsonl")
    result = exporter.export([ReadableSpan(
        name="checkout.start", context=SpanContext(123, 456, False), attributes={},
    )])
    assert result == SpanExportResult.FAILURE
    assert "Local application trace receipt failed" in caplog.text


@pytest.mark.parametrize(
    ("operation_name", "name"),
    [
        ("execute_tool", "checkout.native.tool"),
        ("invoke_agent", "checkout.native.agent"),
        ("create_agent", "checkout.native.agent"),
        ("chat", "checkout.native.model"),
        ("embeddings", "checkout.native.model"),
    ],
)
def test_native_dynamic_names_and_attributes_are_categorized(operation_name, name):
    collector = RecordingExporter()
    SafeExporter(collector).export(
        [
            ReadableSpan(
                name=f"{operation_name} {SECRET}",
                attributes={
                    "gen_ai.operation.name": operation_name,
                    "gen_ai.tool.name": SECRET,
                    "gen_ai.tool.description": SECRET,
                    "gen_ai.tool.call.id": SECRET,
                    "gen_ai.agent.name": SECRET,
                    "gen_ai.request.model": SECRET,
                },
            )
        ]
    )
    assert collector.spans[0].name == name
    assert collector.spans[0].attributes == {"gen_ai.operation.name": operation_name}


@pytest.mark.parametrize("batch_size", [1, 2, 100])
def test_tool_parents_survive_across_export_batches(monkeypatch, batch_size):
    raw = RecordingExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(raw))
    tracer = provider.get_tracer("test.checkout")
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda *args, **kwargs: tracer)
    try:
        with operation("api"):
            with operation("start", "case-id"), operation("model"):
                with tracer.start_as_current_span(
                    f"invoke_agent {SECRET}",
                    attributes={"gen_ai.operation.name": "invoke_agent"},
                ):
                    for tool_name in ("read_order", "read_payment", "read_inventory"):
                        with tracer.start_as_current_span(
                            f"execute_tool {tool_name}",
                            attributes={"gen_ai.operation.name": "execute_tool"},
                        ):
                            with operation(f"tool.{tool_name}"):
                                pass
                    with tracer.start_as_current_span(SECRET):
                        with operation("verification"):
                            pass
    finally:
        provider.shutdown()

    collector = RecordingExporter()
    exporter = SafeExporter(collector)
    # SDK completion order exports children before parents, including separate batches.
    for offset in range(0, len(raw.spans), batch_size):
        exporter.export(raw.spans[offset : offset + batch_size])
    assert len(collector.spans) == len(raw.spans) == 12
    by_id = {span.context.span_id: span for span in collector.spans}
    for original, safe in zip(raw.spans, collector.spans, strict=True):
        assert safe.context == original.context
        assert safe.parent == original.parent
        if safe.parent is not None:
            assert safe.parent.span_id in by_id
        if safe.name.startswith("checkout.tool."):
            assert by_id[safe.parent.span_id].name == "checkout.native.tool"
        assert SECRET not in safe.to_json()
    assert sum(span.name == "checkout.native.tool" for span in by_id.values()) == 3


def test_operation_keeps_interface_hashes_case_and_records_only_error_status(monkeypatch):
    collector = RecordingExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SafeExporter(collector)))
    tracer = provider.get_tracer("test.checkout")
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda *args, **kwargs: tracer)
    try:
        with pytest.raises(RuntimeError, match=SECRET), operation("api", SECRET):
            raise RuntimeError(SECRET)
    finally:
        provider.shutdown()
    span = collector.spans[0]
    assert span.kind is SpanKind.SERVER
    assert span.attributes["checkout.correlation"] == sha256(SECRET.encode()).hexdigest()[:24]
    assert span.status.status_code is StatusCode.ERROR
    assert SECRET not in span.to_json()


@pytest.mark.parametrize("explicit", [False, True])
def test_api_configuration_selects_connection_and_does_not_install_logging(monkeypatch, explicit):
    from azure.monitor.opentelemetry import exporter as azure_exporter

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "environment-connection")
    azure_factory = Mock()
    provider_factory = Mock()
    batch_factory = Mock()
    install_provider = Mock()
    monkeypatch.setattr(azure_exporter, "AzureMonitorTraceExporter", azure_factory)
    monkeypatch.setattr(telemetry, "TracerProvider", provider_factory)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", batch_factory)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", install_provider)
    handlers = list(logging.getLogger().handlers)
    logger_provider = _logs.get_logger_provider()
    provider = (
        telemetry.configure_api_telemetry(connection_string="selected-dotenv-connection")
        if explicit
        else telemetry.configure_api_telemetry()
    )
    azure_factory.assert_called_once_with(
        connection_string="selected-dotenv-connection" if explicit else "environment-connection",
        disable_offline_storage=True,
    )
    assert provider is provider_factory.return_value
    install_provider.assert_called_once_with(provider)
    safe_exporter = batch_factory.call_args.args[0]
    assert isinstance(safe_exporter, SafeExporter)
    assert safe_exporter.delegate is azure_factory.return_value
    assert logging.getLogger().handlers == handlers
    assert _logs.get_logger_provider() is logger_provider


@pytest.mark.parametrize("connection", [None, ""])
def test_explicit_disable_ignores_environment_without_installing_provider(monkeypatch, connection):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "environment-connection")
    provider_factory = Mock()
    monkeypatch.setattr(telemetry, "TracerProvider", provider_factory)
    assert telemetry.configure_api_telemetry(connection_string=connection) is None
    provider_factory.assert_not_called()


def test_no_argument_configuration_without_environment_is_disabled(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    assert telemetry.configure_api_telemetry() is None


def test_exporter_preserves_delegate_lifecycle_and_failure_result():
    delegate = Mock()
    delegate.export.return_value = SpanExportResult.FAILURE
    delegate.force_flush.return_value = False
    exporter = SafeExporter(delegate)
    assert exporter.export([]) is SpanExportResult.SUCCESS
    delegate.export.assert_not_called()
    assert exporter.export([ReadableSpan(name="checkout.api")]) is SpanExportResult.FAILURE
    assert exporter.force_flush(123) is False
    delegate.force_flush.assert_called_once_with(123)
    exporter.shutdown()
    delegate.shutdown.assert_called_once_with()
