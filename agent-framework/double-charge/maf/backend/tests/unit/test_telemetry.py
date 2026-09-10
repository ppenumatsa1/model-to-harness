from __future__ import annotations

import io
import json
import logging
from threading import Event as ThreadEvent
from time import monotonic
from unittest.mock import AsyncMock, Mock

import pytest
from agent_framework import (
    Agent,
    BaseChatClient,
    ChatResponse,
    Executor,
    Message,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)
from agent_framework.observability import OBSERVABILITY_SETTINGS, ChatTelemetryLayer
from azure.monitor.opentelemetry.exporter import ApplicationInsightsSampler, RateLimitedSampler
from maf_double_charge.config import Settings
from maf_double_charge.infrastructure import logging as safe_logging
from maf_double_charge.infrastructure import telemetry
from opentelemetry import trace
from opentelemetry._logs import LogRecord
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Link, SpanContext, Status, StatusCode, TraceFlags, TraceState
from pythonjsonlogger.json import JsonFormatter

SECRET = "RAW-COMPLAINT-prompt-checkpoint-idempotency-password-DO-NOT-EXPORT"


@pytest.fixture(autouse=True)
def restore_logging():
    logging.getLogger("maf_double_charge")
    loggers = [logging.getLogger()] + [
        item
        for item in logging.Logger.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    ]
    original = [
        (
            item,
            list(item.handlers),
            item.level,
            [(h, list(h.filters), h.formatter) for h in item.handlers],
        )
        for item in loggers
    ]
    yield
    for item, handlers, level, filters in original:
        item.handlers[:] = handlers
        item.setLevel(level)
        for log_handler, saved, formatter in filters:
            log_handler.filters[:] = saved
            log_handler.setFormatter(formatter)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        applicationinsights_connection_string=None,
        otel_exporter_otlp_endpoint=None,
        otel_service_name="cutover-api",
        otel_service_version="release-test",
        log_level="INFO",
    )


@pytest.fixture
def provider(monkeypatch):
    value = TracerProvider(
        resource=Resource({"service.name": "hosted-real-role", "unsafe": SECRET}),
        shutdown_on_exit=False,
    )
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: value)
    monkeypatch.setattr(telemetry, "_configured", None)
    safe_logging.clear_log_context()
    yield value
    value.shutdown()
    safe_logging.clear_log_context()


def test_hosted_redacts_before_preexisting_exporter_and_keeps_ownership(provider, settings):
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    provider.shutdown = Mock(wraps=provider.shutdown)
    provider.force_flush = Mock(wraps=provider.force_flush)
    handle = telemetry.configure_telemetry(settings, host="hosted")
    assert telemetry.configure_telemetry(settings, host="hosted") is handle
    parent = SpanContext(123, 456, True, TraceFlags.SAMPLED, TraceState([("vendor", SECRET)]))
    with telemetry.telemetry_context(case_id=SECRET, run_id="run-1", conversation_id="conv-1"):
        with provider.get_tracer("test", attributes={"prompt": SECRET}).start_as_current_span(
            "workflow.run",
            links=[Link(parent, {"tool.arguments": SECRET, "message.type": "standard"})],
        ) as span:
            span.set_attributes(
                {
                    "gen_ai.input.messages": SECRET,
                    "gen_ai.output.messages": SECRET,
                    "gen_ai.system_instructions": SECRET,
                    "checkpoint.body": SECRET,
                    "idempotency_key": SECRET,
                    "connection_string": SECRET,
                    "db.statement": SECRET,
                    "gen_ai.tool.call.arguments": SECRET,
                    "gen_ai.tool.call.result": SECRET,
                    "url.full": f"https://example.org/{SECRET}?key={SECRET}",
                    "gen_ai.usage.input_tokens": 17,
                    "_MS.sampleRate": 25.0,
                }
            )
            span.add_event(
                "exception",
                {
                    "exception.type": "ValueError",
                    "exception.message": SECRET,
                    "exception.stacktrace": SECRET,
                },
            )
            span.add_event(SECRET, {"content": SECRET})
            span.set_status(Status(StatusCode.ERROR, SECRET))
    (exported,) = exporter.get_finished_spans()
    assert SECRET not in exported.to_json()
    assert exported.name == "workflow.run"
    assert exported.status.status_code is StatusCode.ERROR
    assert exported.status.description is None
    assert exported.resource.attributes["service.name"] == "hosted-real-role"
    assert exported.attributes["case_id"] == safe_logging.correlation_id(SECRET)
    assert exported.attributes["gen_ai.usage.input_tokens"] == 17
    assert exported.attributes["_MS.sampleRate"] == 25.0
    assert "gen_ai.usage.output_tokens" not in exported.attributes
    assert exported.links[0].context.trace_id == parent.trace_id
    assert exported.links[0].context.span_id == parent.span_id
    assert not exported.links[0].context.trace_state
    assert exported.links[0].attributes == {"message.type": "standard"}
    assert exported.events[0].attributes == {"exception.type": "ValueError"}
    assert len(exported.events) == 1
    assert not exported.instrumentation_scope.attributes
    handle.shutdown()
    handle.shutdown()
    provider.shutdown.assert_not_called()
    provider.force_flush.assert_not_called()
    assert OBSERVABILITY_SETTINGS.enable_sensitive_data is False
    assert OBSERVABILITY_SETTINGS.enable_message_events is False
    assert OBSERVABILITY_SETTINGS.emit_tool_call_attributes is False


def test_span_names_and_resource_do_not_leak(provider, settings):
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.configure_telemetry(settings, host="hosted")
    with provider.get_tracer("test").start_as_current_span(SECRET):
        pass
    (exported,) = exporter.get_finished_spans()
    assert exported.name == "operation"
    assert SECRET not in exported.to_json()


def test_lazy_hosted_configuration_protects_already_active_platform_request(provider, settings):
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("azure.ai.agentserver")
    with tracer.start_as_current_span(
        "POST /responses",
        kind=trace.SpanKind.SERVER,
        attributes={
            "http.request.method": "POST",
            "http.route": "/responses",
            "gen_ai.input.messages": SECRET,
        },
    ):
        telemetry.configure_telemetry(settings, host="hosted")
        with telemetry.telemetry_context(conversation_id="supplied-conversation", run_id="run-1"):
            with tracer.start_as_current_span("workflow.run"):
                pass
    child, request = exporter.get_finished_spans()
    assert child.parent.span_id == request.context.span_id
    assert request.name == "POST /responses"
    assert request.attributes["run_id"] == safe_logging.correlation_id("run-1")
    assert SECRET not in request.to_json()


def test_separate_requests_share_safe_correlation_not_trace(provider, settings):
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.configure_telemetry(settings, host="hosted")
    tracer = provider.get_tracer("test")
    for command in ("start", "approval", "resume"):
        with tracer.start_as_current_span(command):
            with telemetry.telemetry_context(case_id="case-1", run_id="run-1"):
                with tracer.start_as_current_span("workflow.run"):
                    with telemetry.telemetry_context(conversation_id="conversation-1"):
                        with tracer.start_as_current_span("message.send"):
                            pass
                    assert "conversation_id" not in safe_logging.current_log_context()
        assert safe_logging.current_log_context() == {}
    spans = exporter.get_finished_spans()
    assert len({span.context.trace_id for span in spans}) == 3
    assert {span.attributes["run_id"] for span in spans} == {safe_logging.correlation_id("run-1")}
    messages = [span for span in spans if span.name == "message.send"]
    assert all(span.attributes["conversation_id"] for span in messages)


@pytest.mark.asyncio
async def test_actual_native_workflow_retains_parentage_and_message_links(provider, settings):
    provider.sampler = ApplicationInsightsSampler(1.0)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.configure_telemetry(settings, host="hosted")

    class OfflineClient(ChatTelemetryLayer, BaseChatClient):
        async def _inner_get_response(self, *, messages, stream, options, **kwargs):
            return ChatResponse(
                messages=[Message(role="assistant", contents=[SECRET])],
                model="offline-model",
            )

    agent = Agent(OfflineClient(), name="investigator", instructions=SECRET)

    class First(Executor):
        @handler
        async def process(self, message: str, ctx: WorkflowContext[str]) -> None:
            await agent.run(message)
            await ctx.send_message(message)

    class Last(Executor):
        @handler
        async def process(self, message: str, ctx: WorkflowContext[str, str]) -> None:
            await ctx.yield_output("safe result")

    first, last = First(id="first"), Last(id="last")
    with telemetry.telemetry_context(case_id="case-native", run_id="run-native"):
        workflow = WorkflowBuilder(start_executor=first).add_edge(first, last).build()
        await workflow.run(SECRET)
    spans = exporter.get_finished_spans()
    names = {span.name for span in spans}
    assert "workflow.run" in names
    assert "executor.process first" in names
    assert "executor.process last" in names
    assert "message.send" in names
    assert "chat offline-model" in names
    assert "invoke_agent investigator" in names
    assert any(name.startswith("edge_group.process") for name in names)
    workflow_span = next(span for span in spans if span.name == "workflow.run")
    executors = [span for span in spans if span.name.startswith("executor.process")]
    assert all(span.parent.span_id == workflow_span.context.span_id for span in executors)
    assert any(span.links for span in executors)
    model_span = next(span for span in spans if span.name == "chat offline-model")
    agent_span = next(span for span in spans if span.name == "invoke_agent investigator")
    assert model_span.parent.span_id == agent_span.context.span_id
    assert "gen_ai.usage.input_tokens" not in model_span.attributes
    assert all(SECRET not in span.to_json() for span in spans)
    assert all(
        span.attributes["run_id"] == safe_logging.correlation_id("run-native") for span in spans
    )


@pytest.mark.parametrize("fixed_percentage", [False, True])
def test_sampling_preserves_implicit_parent_chain(
    provider, settings, monkeypatch, fixed_percentage
):
    if fixed_percentage:
        provider.sampler = ApplicationInsightsSampler(1.0)
    else:
        sampler = RateLimitedSampler(5.0)
        # Reproduce a rate change without relying on timing or random trace IDs.
        monkeypatch.setattr(
            sampler._sampling_percentage_generator,
            "get",
            Mock(side_effect=[100.0, 0.0, 100.0]),
        )
        provider.sampler = sampler
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.configure_telemetry(settings, host="hosted")
    tracer = provider.get_tracer("implicit-parent-sampling")
    with tracer.start_as_current_span("invoke_agent"):
        with tracer.start_as_current_span("workflow.run"):
            with tracer.start_as_current_span("executor.process normalize_complaint") as child:
                child.set_attribute("gen_ai.input.messages", SECRET)
    spans = exporter.get_finished_spans()
    ids = {span.context.span_id for span in spans}
    orphans = [span.name for span in spans if span.parent and span.parent.span_id not in ids]
    assert ("workflow.run" in {span.name for span in spans}) is fixed_percentage
    assert orphans == ([] if fixed_percentage else ["executor.process normalize_complaint"])
    assert len({span.context.trace_id for span in spans}) == 1
    assert all(SECRET not in span.to_json() for span in spans)


@pytest.mark.asyncio
@pytest.mark.parametrize("sdk_tracing", [True, False])
async def test_sdk_setup_tracing_opt_out_preserves_native_parentage(
    provider, monkeypatch, sdk_tracing
):
    from azure.ai.projects.aio import AIProjectClient

    monkeypatch.setenv("AZURE_TRACING_ENABLED", str(sdk_tracing).lower())
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("native-instrumentation")
    with tracer.start_as_current_span("workflow.run"):
        async with AIProjectClient(
            endpoint="https://example.invalid/api/projects/test",
            credential=AsyncMock(),
        ) as project:
            async with project.get_openai_client():
                pass
        with tracer.start_as_current_span("executor.process normalize_complaint"):
            pass
    spans = exporter.get_finished_spans()
    names = {span.name for span in spans}
    assert ("AIProjectClient.get_openai_client" in names) is sdk_tracing
    workflow = next(span for span in spans if span.name == "workflow.run")
    executor = next(span for span in spans if span.name == "executor.process normalize_complaint")
    assert executor.parent.span_id == workflow.context.span_id


def test_safe_log_exporter_drops_body_extras_and_retains_trace_correlation():
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider(shutdown_on_exit=False)
    provider.add_log_record_processor(telemetry.SafetyLogProcessor())
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    provider.get_logger("maf_double_charge").emit(
        LogRecord(
            body=SECRET,
            trace_id=123,
            span_id=456,
            attributes={
                "event_type": "run.started",
                "case_id": SECRET,
                "idempotency_key": SECRET,
                "exception.message": SECRET,
                "tool.result": SECRET,
            },
        )
    )
    (record,) = exporter.get_finished_logs()
    assert record.log_record.body == "run.started"
    assert record.log_record.trace_id == 123
    assert record.log_record.span_id == 456
    assert record.log_record.attributes == {
        "event_type": "run.started",
        "case_id": safe_logging.correlation_id(SECRET),
    }
    assert provider.force_flush(timeout_millis=1000)
    provider.shutdown()


def test_console_redaction_and_configuration_preserve_host_handlers(monkeypatch):
    root = logging.getLogger()
    output = io.StringIO()
    platform = logging.StreamHandler(output)
    platform.setFormatter(JsonFormatter())
    monkeypatch.setattr(root, "handlers", [platform])
    monkeypatch.setattr(root, "level", logging.INFO)
    safe_logging.configure_logging()
    safe_logging.configure_logging()
    assert platform in root.handlers
    assert len(root.handlers) == 2
    with safe_logging.log_context(case_id=SECRET):
        try:
            raise ValueError(SECRET)
        except ValueError:
            logging.getLogger("maf_double_charge.test").error(
                "Complaint: %s",
                SECRET,
                exc_info=True,
                stack_info=True,
                extra={
                    "event_type": "run.failed",
                    "idempotency_key": SECRET,
                    "prompt": SECRET,
                    "checkpoint_id": SECRET,
                },
            )
    line = output.getvalue()
    assert SECRET not in line
    record = json.loads(line)
    assert record["message"] == "run.failed"
    assert record["case_id"] == safe_logging.correlation_id(SECRET)
    assert record["error.type"] == "ValueError"
    assert "idempotency_key" not in record
    assert "exc_info" not in record


@pytest.mark.parametrize(
    ("path", "method", "status"),
    [
        ("/health/live", "GET", 200),
        (f"/runs/{SECRET}?complaint={SECRET}&api_key={SECRET}", "POST", 400),
        (f"/health/ready?token={SECRET}", SECRET, 503),
    ],
)
@pytest.mark.parametrize("use_subclass", [False, True])
def test_uvicorn_access_logging_uses_safe_compatible_formatter(
    monkeypatch, capsys, path, method, status, use_subclass
):
    from uvicorn.config import LOGGING_CONFIG
    from uvicorn.logging import AccessFormatter

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    config = LOGGING_CONFIG["formatters"]["access"]
    assert config["()"] == "uvicorn.logging.AccessFormatter"

    class CustomAccessFormatter(AccessFormatter):
        pass

    formatter_type = CustomAccessFormatter if use_subclass else AccessFormatter
    handler.setFormatter(formatter_type(fmt=config["fmt"], use_colors=False))
    format_error = Mock(wraps=handler.handleError)
    monkeypatch.setattr(handler, "handleError", format_error)
    access_logger = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(access_logger, "handlers", [handler])
    monkeypatch.setattr(access_logger, "propagate", False)
    monkeypatch.setattr(access_logger, "disabled", False)
    monkeypatch.setattr(access_logger, "level", logging.INFO)

    safe_logging.configure_logging()
    safe_logging.configure_logging()
    with safe_logging.log_context(run_id="run-access"):
        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            f"client-{SECRET}",
            method,
            path,
            f"1.1-{SECRET}",
            status,
            extra={"prompt": SECRET},
        )

    format_error.assert_not_called()
    assert access_logger.handlers == [handler]
    assert capsys.readouterr().err == ""
    line = output.getvalue()
    assert SECRET not in line
    event = json.loads(line)
    assert event["message"] == "http.request.completed"
    assert event["http.request.method"] == ("_OTHER" if method == SECRET else method)
    assert event["http.response.status_code"] == status
    assert event["run_id"] == safe_logging.correlation_id("run-access")
    assert "client_addr" not in event
    assert "request_line" not in event
    assert "prompt" not in event
    assert len(handler.filters) == 1


def test_logging_startup_does_not_import_uvicorn(monkeypatch):
    import builtins
    import sys

    original_import = builtins.__import__
    attempts = []

    def without_uvicorn(name, *args, **kwargs):
        if name == "uvicorn" or name.startswith("uvicorn."):
            attempts.append(name)
            raise ModuleNotFoundError("Uvicorn is not installed in the hosted environment")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "uvicorn.logging", raising=False)
    monkeypatch.setattr(builtins, "__import__", without_uvicorn)
    safe_logging.configure_logging("INFO")
    safe_logging.protect_log_handlers()
    assert attempts == []


def test_owned_shutdown_flushes_all_once_even_after_failure():
    first, second = Mock(), Mock()
    first.force_flush.side_effect = RuntimeError(SECRET)
    first.shutdown.side_effect = RuntimeError(SECRET)
    handle = telemetry.TelemetryHandle("otlp", (first, second))
    handle.shutdown()
    handle.shutdown()
    first.force_flush.assert_called_once_with(timeout_millis=5000)
    second.force_flush.assert_called_once_with(timeout_millis=5000)
    first.shutdown.assert_called_once()
    second.shutdown.assert_called_once()


@pytest.mark.parametrize("blocked_operation", ["force_flush", "shutdown"])
def test_shutdown_wait_is_bounded_even_when_exporter_ignores_timeout(
    monkeypatch, blocked_operation
):
    release, finished = ThreadEvent(), ThreadEvent()
    slow, fast = Mock(), Mock()
    monkeypatch.setattr(telemetry, "_EXPORT_TIMEOUT_MILLIS", 20)

    def wait(**kwargs):
        release.wait()
        finished.set()
        return True

    getattr(slow, blocked_operation).side_effect = wait
    handle = telemetry.TelemetryHandle("otlp", (slow, fast))
    try:
        start = monotonic()
        handle.shutdown()
        assert monotonic() - start < 0.5
        fast.force_flush.assert_called_once_with(timeout_millis=20)
        fast.shutdown.assert_called_once()
        if blocked_operation == "force_flush":
            slow.shutdown.assert_not_called()
        handle.shutdown()
        fast.shutdown.assert_called_once()
    finally:
        release.set()
        assert finished.wait(1)


def test_disabled_does_not_claim_provider_or_export(monkeypatch, settings):
    monkeypatch.setattr(telemetry, "_configured", None)
    monkeypatch.setattr(trace, "set_tracer_provider", Mock())
    handle = telemetry.configure_telemetry(settings)
    assert handle.mode == "disabled"
    handle.shutdown()
    assert telemetry.configure_telemetry(settings) is handle
    trace.set_tracer_provider.assert_not_called()


def test_hosted_without_initialized_platform_fails_clearly(monkeypatch, settings):
    monkeypatch.setattr(telemetry, "_configured", None)
    monkeypatch.setattr(trace, "get_tracer_provider", trace.ProxyTracerProvider)
    with pytest.raises(RuntimeError, match="hosted platform"):
        telemetry.configure_telemetry(settings, host="hosted")


def test_api_never_overrides_platform_provider(provider, settings):
    settings.applicationinsights_connection_string = "InstrumentationKey=not-a-real-key"
    with pytest.raises(RuntimeError, match="existing tracer provider"):
        telemetry.configure_telemetry(settings)


def test_hosted_safety_rejects_untested_sdk_family(monkeypatch, provider, settings):
    monkeypatch.setattr(telemetry, "version", lambda package: "1.45.0")
    with pytest.raises(RuntimeError, match="tested OpenTelemetry SDK"):
        telemetry.configure_telemetry(settings, host="hosted")


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://localhost",
        "https://user:password@example.org",
        "https://example.org?key=secret",
        "https://example.org#secret",
    ],
)
def test_otlp_rejects_credentials_and_unsupported_endpoints(endpoint):
    with pytest.raises(ValueError, match="without credentials or query"):
        telemetry._otlp_endpoints(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:4318",
        "http://localhost:4318/",
        "http://localhost:4318/v1/traces",
    ],
)
def test_otlp_base_and_original_trace_endpoint_supported(endpoint):
    assert telemetry._otlp_endpoints(endpoint) == {
        kind: f"http://localhost:4318/v1/{kind}" for kind in ("traces", "logs", "metrics")
    }


@pytest.mark.parametrize("destination", ["azure_monitor", "otlp"])
@pytest.mark.parametrize("setup_timing", ["early", "lifespan"])
def test_real_export_configuration_scoped_request_logs_and_metrics(
    monkeypatch, settings, destination, setup_timing
):
    import socket
    from contextlib import asynccontextmanager

    from azure.monitor.opentelemetry import _configure as distro
    from azure.monitor.opentelemetry import exporter as azure_exporter
    from azure.monitor.opentelemetry._constants import _ALL_SUPPORTED_INSTRUMENTED_LIBRARIES
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry import metrics
    from opentelemetry._logs import _internal as log_api
    from opentelemetry.exporter.otlp.proto.http import _log_exporter as otlp_logs
    from opentelemetry.exporter.otlp.proto.http import metric_exporter as otlp_metrics
    from opentelemetry.exporter.otlp.proto.http import trace_exporter as otlp_traces
    from opentelemetry.metrics import _internal as metric_api
    from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult
    from opentelemetry.util._once import Once

    # Isolate process-global SDK providers; production never resets these globals.
    for module, prefix in ((trace, "TRACER"), (metric_api, "METER"), (log_api, "LOGGER")):
        monkeypatch.setattr(module, f"_{prefix}_PROVIDER", None)
        monkeypatch.setattr(module, f"_{prefix}_PROVIDER_SET_ONCE", Once())
    monkeypatch.setattr(metric_api, "_PROXY_METER_PROVIDER", metric_api._ProxyMeterProvider())
    monkeypatch.setattr(trace, "_PROXY_TRACER_PROVIDER", trace.ProxyTracerProvider())
    monkeypatch.setattr(log_api, "_PROXY_LOGGER_PROVIDER", log_api.ProxyLoggerProvider())
    monkeypatch.setattr(telemetry, "_configured", None)
    monkeypatch.setattr(distro, "get_configuration_manager", lambda: None)
    monkeypatch.setenv("OTEL_EXPERIMENTAL_RESOURCE_DETECTORS", "")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "parentbased_always_on")
    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "azure_monitor")
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "azure_monitor")
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "azure_monitor")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST", ".*")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE", ".*")
    network = Mock(side_effect=AssertionError("Unexpected network access in in-memory export test"))
    monkeypatch.setattr(socket.socket, "connect", network)
    assert set(_ALL_SUPPORTED_INSTRUMENTED_LIBRARIES) <= set(telemetry._INSTRUMENTATIONS)

    spans, logs = InMemorySpanExporter(), InMemoryLogRecordExporter()
    observed = {}

    class MemoryMetrics(MetricExporter):
        def __init__(self):
            super().__init__()
            self.data = []

        def export(self, metrics_data, timeout_millis=10000, **kwargs):
            self.data.append(metrics_data)
            return MetricExportResult.SUCCESS

        def shutdown(self, timeout_millis=30000, **kwargs):
            pass

        def force_flush(self, timeout_millis=10000):
            return True

    metric_exporter = MemoryMetrics()

    def factory(signal, exporter):
        def create(**kwargs):
            observed[signal] = kwargs
            return exporter

        return create

    # Exercise actual distro/OTLP providers, batching, instrumentation and export.
    # Only network exporter construction is replaced by in-memory exporters.
    monkeypatch.setattr(distro, "AzureMonitorTraceExporter", factory("traces", spans))
    monkeypatch.setattr(distro, "AzureMonitorMetricExporter", factory("metrics", metric_exporter))
    monkeypatch.setattr(azure_exporter, "AzureMonitorLogExporter", factory("logs", logs))
    monkeypatch.setattr(otlp_traces, "OTLPSpanExporter", factory("traces", spans))
    monkeypatch.setattr(otlp_metrics, "OTLPMetricExporter", factory("metrics", metric_exporter))
    monkeypatch.setattr(otlp_logs, "OTLPLogExporter", factory("logs", logs))
    if destination == "azure_monitor":
        settings.applicationinsights_connection_string = (
            "InstrumentationKey=00000000-0000-0000-0000-000000000001"
        )
    else:
        settings.otel_exporter_otlp_endpoint = "http://localhost:4318"
    # Previous API/runtime tests may leave the process root logger at ERROR.
    # Match production startup instead of relying on pytest's ambient log level.
    logging.getLogger().setLevel(logging.ERROR)
    handle = None
    if setup_timing == "early":
        safe_logging.configure_logging(settings.log_level)
        handle = telemetry.configure_telemetry(settings)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal handle
        safe_logging.configure_logging(settings.log_level)
        handle = telemetry.configure_telemetry(settings)
        yield

    app = FastAPI(lifespan=lifespan)

    @app.post("/commands/{command}")
    async def command(command: str):
        with telemetry.telemetry_context(case_id="case-export", run_id="run-export"):
            with trace.get_tracer("test").start_as_current_span("workflow.run"):
                logging.getLogger("maf_double_charge").warning(
                    SECRET,
                    extra={"event_type": "run.started", "idempotency_key": SECRET},
                )
        return {"ok": True}

    if handle is None:
        telemetry.instrument_api_app(app, settings)
        telemetry.instrument_api_app(app, settings)
        assert observed == {}
    else:
        handle.instrument_app(app)
        handle.instrument_app(app)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/commands/start?complaint={SECRET}",
                json={"prompt": SECRET},
                headers={"x-credential": SECRET},
            )
            assert response.status_code == 200
        assert telemetry.configure_telemetry(settings) is handle
        assert handle.mode == destination
        assert set(observed) == {"traces", "logs", "metrics"}
        meter = metrics.get_meter("agent_framework")
        meter.create_histogram("gen_ai.client.token.usage").record(
            19, {"gen_ai.token.type": "input", "gen_ai.prompt": SECRET}
        )
        meter.create_counter("unrestricted.payload.metric").add(1, {"content": SECRET})
        assert handle.force_flush()
        exported = spans.get_finished_spans()
        request_spans = [span for span in exported if span.kind is trace.SpanKind.SERVER]
        assert len(request_spans) == 1
        (request,) = request_spans
        assert request.name == "POST /commands/{command}"
        assert request.attributes["run_id"] == safe_logging.correlation_id("run-export")
        child = next(span for span in exported if span.name == "workflow.run")
        assert child.parent.span_id == request.context.span_id
        assert child.resource.attributes["service.name"] == "cutover-api"
        assert child.resource.attributes["service.version"] == "release-test"
        assert all(SECRET not in span.to_json() for span in exported)
        assert len(logs.get_finished_logs()) == 1
        log = logs.get_finished_logs()[0].log_record
        assert log.body == "run.started"
        assert log.trace_id == request.context.trace_id
        assert SECRET not in str(log.attributes)
        exported_metrics = [
            metric
            for batch in metric_exporter.data
            for resource in batch.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        ]
        assert "gen_ai.client.token.usage" in {metric.name for metric in exported_metrics}
        assert "unrestricted.payload.metric" not in {metric.name for metric in exported_metrics}
        assert SECRET not in str(metric_exporter.data)
        if destination == "azure_monitor":
            from azure.monitor.opentelemetry.exporter.export.trace._exporter import (
                _convert_span_to_envelope,
            )

            envelope = _convert_span_to_envelope(request)
            assert envelope.tags["ai.cloud.role"] == "cutover-api"
            assert envelope.tags["ai.application.ver"] == "release-test"
            assert envelope.tags["ai.operation.id"] == f"{request.context.trace_id:032x}"
            assert envelope.data.base_data.properties["run_id"] == (
                safe_logging.correlation_id("run-export")
            )
            assert all(
                observed["traces"][key] is False
                for key in ("enable_live_metrics", "enable_performance_counters")
            )
            assert observed["traces"]["disable_offline_storage"] is True
        else:
            assert observed["traces"]["endpoint"] == "http://localhost:4318/v1/traces"
        with pytest.raises(RuntimeError, match="restart"):
            telemetry.configure_telemetry(settings.model_copy(update={"app_env": "changed"}))
    finally:
        if handle is not None:
            handle.shutdown()
    network.assert_not_called()
    with pytest.raises(RuntimeError, match="restart"):
        telemetry.configure_telemetry(settings)
