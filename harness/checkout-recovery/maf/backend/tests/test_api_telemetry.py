import pytest
from checkout_recovery_maf.api.app import create_app
from checkout_recovery_maf.config import Settings
from checkout_recovery_maf.infrastructure import telemetry
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode


@pytest.fixture
def spans(monkeypatch):
    collector = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(telemetry.SafeExporter(collector)))
    tracer = provider.get_tracer("test.checkout")
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda *args, **kwargs: tracer)
    yield collector
    provider.shutdown()


@pytest.mark.parametrize(
    ("method", "status", "retained"),
    [
        ("GET", 200, False),
        ("HEAD", 200, False),
        ("OPTIONS", 204, False),
        ("GET", 304, False),
        ("GET", 404, True),
        ("GET", 503, True),
        ("POST", 201, True),
        ("POST", 500, True),
    ],
)
def test_only_successful_read_roots_are_suppressed(spans, method, status, retained):
    with telemetry.operation("api"):
        telemetry.record_api_response(method, status)
    exported = spans.get_finished_spans()
    assert bool(exported) is retained
    if retained:
        assert exported[0].attributes["http.response.status_code"] == status
        assert (exported[0].status.status_code is StatusCode.ERROR) is (status >= 400)
        assert "checkout.suppress_successful_read" not in exported[0].attributes


def test_errors_and_native_spans_are_never_suppressed(spans):
    tracer = telemetry.trace.get_tracer("test.checkout")
    for name in ("checkout.api", "checkout.model", "checkout.tool.read_order"):
        with tracer.start_as_current_span(name) as span:
            span.set_attribute("checkout.suppress_successful_read", True)
            if name == "checkout.api":
                span.set_status(Status(StatusCode.ERROR))
    assert len(spans.get_finished_spans()) == 3


def test_real_middleware_silences_polls_but_preserves_commands_and_failures(spans):
    settings = Settings(
        _env_file=None,
        execution_mode="scripted",
        api_token="test-token",
        applicationinsights_connection_string=None,
    )
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/api/health/live").status_code == 200
        assert not spans.get_finished_spans()
        assert client.get("/api/cases").status_code == 401
        assert spans.get_finished_spans()[-1].status.status_code is StatusCode.ERROR
        spans.clear()
        client.headers["X-Checkout-Token"] = "test-token"
        started = client.post(
            "/api/cases", json={"fixture_id": "recoverable-inventory-reservation"}
        )
        assert started.status_code == 201
        exported = spans.get_finished_spans()
        assert any(span.name == "checkout.start" for span in exported)
        assert exported[-1].name == "checkout.api"
        ids = {span.context.span_id for span in exported}
        assert all(span.parent is None or span.parent.span_id in ids for span in exported)
        spans.clear()
        case_id = started.json()["case_id"]
        for path in ("", "/events", "/workspace-artifact"):
            assert client.get(f"/api/cases/{case_id}{path}").status_code == 200
        assert not spans.get_finished_spans()
        assert client.get("/api/cases/missing").status_code == 404
        assert spans.get_finished_spans()[-1].status.status_code is StatusCode.ERROR
