import asyncio
import logging
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.application.records import ApprovalRequest, StartCaseRequest
from model_to_harness_langgraph.application.service import WorkflowService
from model_to_harness_langgraph.graph.runner import DoubleChargeWorkflow
from model_to_harness_langgraph.infrastructure import model_client, telemetry
from model_to_harness_langgraph.infrastructure.domain_gateway import ToolResult
from model_to_harness_langgraph.infrastructure.logging import SafeLogFilter
from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
from model_to_harness_langgraph.testing.fakes import FakeDomainGateway, FakeModel
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON


@pytest.fixture(params=["otel", "azure"])
def captured(monkeypatch, request):
    from azure.monitor.opentelemetry.exporter import ApplicationInsightsSampler

    exporter = InMemorySpanExporter()
    sampler = ALWAYS_ON if request.param == "otel" else ApplicationInsightsSampler(1.0)
    provider = TracerProvider(sampler=sampler)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    yield exporter
    provider.shutdown()


async def test_actual_parallel_tool_spans_retries_interrupt_and_safe_parentage(captured):
    active = set()
    both_started = asyncio.Event()

    class Gateway(FakeDomainGateway):
        read_calls = 0

        async def load_account(self, run_id, customer_id, scenario_id):
            self.read_calls += 1
            if self.read_calls == 1:
                return ToolResult(ok=False, transient=True, code="TRANSIENT_BILLING_READ")
            return await super().load_account(run_id, customer_id, "duplicate_confirmed")

        async def validate_billing(self, *args):
            active.add("billing")
            if len(active) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 2)
            return await super().validate_billing(*args)

        async def validate_policy(self, *args):
            active.add("policy")
            if len(active) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 2)
            return await super().validate_policy(*args)

    class Model(FakeModel):
        calls = 0

        async def normalize(self, complaint):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("SECRET complaint and connection string")
            return await super().normalize(complaint)

    audit = InMemoryAuditRepository()
    workflow = DoubleChargeWorkflow(
        audit=audit, gateway=Gateway(), model=Model(), checkpointer=InMemorySaver()
    )
    service = WorkflowService(workflow, audit)
    result = await service.start(
        StartCaseRequest(
            complaint="SECRET raw complaint",
            customer_id="SECRET customer",
            scenario_id="transient_failure",
            existing_case_id="sensitive-case",
        )
    )
    before_resume = captured.get_finished_spans()
    normalized = [s for s in before_resume if s.name == "workflow.node.normalize_complaint"]
    assert len(normalized) == 2
    assert normalized[0].status.is_ok is False
    assert normalized[0].attributes["error.type"] == "ConnectionError"
    assert len([s for s in before_resume if s.name == "workflow.node.load_account"]) == 2
    approval_span = next(s for s in before_resume if s.name == "workflow.node.request_approval")
    assert approval_span.attributes["workflow.interrupted"] is True
    await service.submit_approval(
        result.case_id,
        ApprovalRequest(
            checkpoint_id=result.checkpoint_id, decision="approve", reviewer_id="SECRET reviewer"
        ),
    )
    await service.resume(result.case_id)
    spans = captured.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans}
    for span in spans:
        if span.name.startswith("workflow.node."):
            assert by_id[span.parent.span_id].name == "workflow.run"
        if span.name.startswith("execute_tool "):
            assert by_id[span.parent.span_id].name.startswith("workflow.node.")
    branches = [
        s
        for s in spans
        if s.name in {"workflow.node.billing_validation", "workflow.node.policy_validation"}
    ]
    assert len(branches) == 2 and branches[0].parent == branches[1].parent
    assert max(s.start_time for s in branches) < min(s.end_time for s in branches)
    serialized = repr([(s.name, dict(s.attributes), s.events, s.status.description) for s in spans])
    assert "SECRET" not in serialized and "sensitive-case" not in serialized
    assert "durable_audit_projection" not in serialized


async def test_model_span_wraps_actual_inference_and_real_usage(monkeypatch, captured):
    invoked = asyncio.Event()
    release = asyncio.Event()

    class Chat:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, messages):
            invoked.set()
            await release.wait()
            return SimpleNamespace(
                content="safe summary", usage_metadata={"input_tokens": 11, "output_tokens": 4}
            )

    monkeypatch.setattr(model_client, "AzureChatOpenAI", Chat)
    monkeypatch.setattr(model_client, "get_bearer_token_provider", lambda *_: object())
    from model_to_harness_langgraph.config import Settings

    model = model_client.FoundryComplaintModel(
        Settings(azure_openai_endpoint="https://example.test", azure_openai_deployment="model"),
        credential=object(),
        sync_credential=object(),
        http_client=object(),
        http_async_client=object(),
    )

    async def invoke():
        with telemetry.execution_span("workflow.node.normalize_complaint"):
            return await model.normalize("SECRET content")

    task = asyncio.create_task(invoke())
    await asyncio.wait_for(invoked.wait(), 2)
    assert not captured.get_finished_spans()
    release.set()
    assert await task == "safe summary"
    model_span, node_span = captured.get_finished_spans()
    assert model_span.parent.span_id == node_span.context.span_id
    assert model_span.attributes["gen_ai.usage.input_tokens"] == 11
    assert model_span.attributes["gen_ai.usage.output_tokens"] == 4
    assert "SECRET" not in repr(dict(model_span.attributes))


def test_hosted_provider_is_borrowed_and_never_shutdown(monkeypatch):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "configured")
    provider = SimpleNamespace(sampler=ALWAYS_ON)
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    assert telemetry.configure_telemetry(hosted=True).providers == ()
    telemetry.configure_telemetry(hosted=True).close()
    provider.sampler = ALWAYS_OFF
    with pytest.raises(RuntimeError, match="complete"):
        telemetry.configure_telemetry(hosted=True)


def test_content_capture_rejected_and_log_payloads_removed(monkeypatch):
    monkeypatch.setenv("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "true")
    with pytest.raises(RuntimeError, match="capture"):
        telemetry.configure_telemetry(hosted=True)
    record = logging.makeLogRecord(
        {
            "msg": "SECRET %s",
            "args": ("credential",),
            "prompt": "SECRET",
            "exc_text": "SECRET traceback",
            "name": "thirdparty",
            "levelno": logging.ERROR,
        }
    )
    assert SafeLogFilter().filter(record)
    assert "SECRET" not in repr(record.__dict__)


def test_api_partial_exporter_startup_closes_only_new_owned_providers(monkeypatch):
    import azure.monitor.opentelemetry

    previous = object()
    active = [previous]
    calls = []

    class Provider:
        sampler = ALWAYS_ON

        def force_flush(self):
            calls.append("flush")

        def shutdown(self):
            calls.append("shutdown")

    def configure(**kwargs):
        assert kwargs["sampling_ratio"] == 1.0
        assert kwargs["logger_name"] == "model_to_harness_langgraph"
        assert kwargs["instrumentation_options"]["httpx"]["enabled"] is False
        active[0] = Provider()
        raise RuntimeError("exporter configuration failed")

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "configured")
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: active[0])
    monkeypatch.setattr(azure.monitor.opentelemetry, "configure_azure_monitor", configure)
    with pytest.raises(RuntimeError, match="exporter configuration"):
        telemetry.configure_telemetry()
    assert calls == ["flush", "shutdown"]


def test_telemetry_shutdown_continues_after_one_provider_failure():
    calls = []

    class Provider:
        def __init__(self, name, fail=False):
            self.name, self.fail = name, fail

        def force_flush(self):
            calls.append(f"flush-{self.name}")
            if self.fail:
                raise RuntimeError("flush failed")

        def shutdown(self):
            calls.append(f"shutdown-{self.name}")

    owned = telemetry.Telemetry((Provider("first"), Provider("second", True)))
    with pytest.raises(RuntimeError, match="flush failed"):
        owned.close()
    assert calls == ["flush-second", "shutdown-second", "flush-first", "shutdown-first"]
    owned.close()
    assert len(calls) == 4


def test_api_request_spans_use_route_templates_without_urls_or_payloads(monkeypatch, captured):
    from fastapi.testclient import TestClient
    from model_to_harness_langgraph.api.app import create_app
    from model_to_harness_langgraph.config import Settings

    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    app = create_app(
        settings=Settings(_env_file=None),
        audit=InMemoryAuditRepository(),
        gateway=FakeDomainGateway(),
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    )
    with TestClient(app) as client:
        started = client.post(
            "/api/cases",
            json={
                "complaint": "SECRET complaint",
                "customer_id": "SECRET customer",
                "idempotency_key": "SECRET key",
            },
        )
        assert started.status_code == 201
        case_id = started.json()["case_id"]
        assert client.get(f"/api/cases/{case_id}?token=SECRET").status_code == 200
    spans = captured.get_finished_spans()
    requests = [span for span in spans if span.name == "http.request"]
    assert {span.attributes["http.route"] for span in requests} == {
        "/api/cases",
        "/api/cases/{case_id}",
    }
    serialized = repr([(dict(s.attributes), s.events, s.status.description) for s in spans])
    assert "SECRET" not in serialized and case_id not in serialized


def test_hosted_policy_checks_actual_transport_state_not_just_opt_out_environment(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("OTEL_PYTHON_DISABLED_INSTRUMENTATIONS", "requests,urllib3,httpx")
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: SimpleNamespace(sampler=ALWAYS_ON))
    loaded = []
    states = {"requests": True, "urllib3": False, "httpx": False, "langchain": True, "openai": True}

    def entry(name):
        def load():
            loaded.append(name)
            return lambda: SimpleNamespace(is_instrumented_by_opentelemetry=states[name])

        return SimpleNamespace(name=name, load=load)

    monkeypatch.setattr(
        telemetry, "entry_points", lambda **kwargs: [entry(name) for name in states]
    )
    with pytest.raises(RuntimeError, match="transport instrumentation is active: requests"):
        telemetry.verify_telemetry_policy(hosted=True)
    states["requests"] = False
    telemetry.verify_telemetry_policy(hosted=True)
    assert set(loaded) == {"requests", "urllib3", "httpx"}
    assert states["langchain"] and states["openai"]


def test_actual_public_instrumentor_state_is_enforced_without_provider_replacement(monkeypatch):
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    provider = TracerProvider(sampler=ALWAYS_ON)
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    instrumentor = RequestsInstrumentor()
    assert not instrumentor.is_instrumented_by_opentelemetry
    original_provider = trace.get_tracer_provider()
    try:
        instrumentor.instrument(tracer_provider=provider)
        with pytest.raises(RuntimeError, match="transport instrumentation is active: requests"):
            telemetry.verify_telemetry_policy(hosted=True)
        assert trace.get_tracer_provider() is original_provider
        instrumentor.uninstrument()
        telemetry.verify_telemetry_policy(hosted=True)
    finally:
        if instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.uninstrument()
        provider.shutdown()


def test_otlp_only_hosted_runtime_requires_initialized_complete_sampler(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.invalid")
    monkeypatch.setattr(telemetry, "entry_points", lambda **kwargs: [])
    provider = SimpleNamespace()
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    with pytest.raises(RuntimeError, match="initialized"):
        telemetry.configure_telemetry(hosted=True)
    provider.sampler = ALWAYS_OFF
    with pytest.raises(RuntimeError, match="complete"):
        telemetry.configure_telemetry(hosted=True)
    provider.sampler = ALWAYS_ON
    assert telemetry.configure_telemetry(hosted=True).providers == ()


@pytest.mark.parametrize(
    "key,prohibited",
    [
        ("gen_ai.input.messages", True),
        ("gen_ai.output_messages", True),
        ("gen_ai.system.instructions", True),
        ("tool.arguments", True),
        ("tool_result", True),
        ("db.connection_string", True),
        ("http.request.header.authorization", True),
        ("checkpoint.payload", True),
        ("langchain.outputs", True),
        ("gen_ai.usage.input_tokens", False),
        ("gen_ai.usage.output_tokens", False),
        ("workflow.error_type", False),
    ],
)
def test_privacy_query_key_contract_covers_dotted_and_underscored_fields(key, prohibited):
    import re
    from pathlib import Path

    directory = Path(__file__).resolve().parents[2] / "observability"
    for name in ("trace-safety.kql", "release-privacy.kql"):
        query = (directory / name).read_text()
        pattern = re.search(r'attributeKey matches regex @"([^"]+)"', query)
        assert pattern is not None
        assert bool(re.search(pattern[1], key)) is prohibited
