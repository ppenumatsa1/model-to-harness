from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.metadata import entry_points, version
from threading import Event as ThreadEvent
from threading import RLock, Thread
from time import monotonic
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from maf_double_charge.config import Settings
from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider, set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LogRecordProcessor, ReadWriteLogRecord
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import Link, Status

from .logging import (
    correlation_id,
    current_log_context,
    log_context,
    protect_log_handlers,
    safe_log_attributes,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)
_lock = RLock()
_configured: tuple[tuple[Any, ...], TelemetryHandle] | None = None
_EXPORT_TIMEOUT_MILLIS = 5000
_TOKEN = re.compile(r"[A-Za-z0-9_.:/-]{1,160}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CORRELATIONS = frozenset(
    {
        "case_id",
        "run_id",
        "conversation_id",
        "response_id",
        "gen_ai.conversation.id",
        "gen_ai.response.id",
        "workflow.id",
    }
)
_TEXT_ATTRIBUTES = frozenset(
    {
        "workflow.name",
        "executor.id",
        "executor.type",
        "edge_group.type",
        "edge_group.id",
        "message.source_id",
        "message.target_id",
        "message.type",
        "message.payload_type",
        "message.destination_executor_id",
        "gen_ai.operation.name",
        "gen_ai.system",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.agent.name",
        "gen_ai.agent.id",
        "gen_ai.tool.name",
        "gen_ai.tool.type",
        "error.type",
        "exception.type",
        "http.request.method",
        "http.method",
        "network.protocol.version",
        "network.protocol.name",
        "server.address",
        "node",
        "transition",
        "event_type",
    }
)
_NUMBER_ATTRIBUTES = frozenset(
    {
        "http.response.status_code",
        "http.status_code",
        "server.port",
        "retry_attempt",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.cache_creation.input_tokens",
        "gen_ai.usage.cache_read.input_tokens",
        "gen_ai.usage.reasoning.output_tokens",
        "gen_ai.request.max_tokens",
    }
)
_RESOURCE_ATTRIBUTES = frozenset(
    {
        "service.name",
        "service.namespace",
        "service.version",
        "service.instance.id",
        "deployment.environment",
        "deployment.environment.name",
        "telemetry.sdk.name",
        "telemetry.sdk.language",
        "telemetry.sdk.version",
        "cloud.provider",
        "cloud.platform",
        "cloud.region",
        "cloud.resource_id",
        "microsoft.agent.id",
        "microsoft.agent.name",
        "microsoft.agent.version",
    }
)
_EVENT_NAMES = frozenset(
    {
        "exception",
        "workflow.started",
        "workflow.completed",
        "workflow.error",
        "build.started",
        "build.validation_completed",
        "build.completed",
        "build.error",
        "edge_group.delivered",
    }
)
_NATIVE_NAME = re.compile(
    r"(?:workflow\.(?:run|build)|message\.send|"
    r"(?:executor\.process|edge_group\.process|chat|invoke_agent|execute_tool)"
    r" [A-Za-z0-9_.-]{1,120})\Z"
)
_ROUTE = re.compile(r"/(?:[a-zA-Z0-9_-]+|\{[a-zA-Z0-9_]+\}|/)*\Z")
_INSTRUMENTATIONS = (
    "azure_sdk",
    "django",
    "fastapi",
    "flask",
    "psycopg2",
    "requests",
    "urllib",
    "urllib3",
    "httpx",
    "httpx2",
)


def _safe_attributes(values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in (values or {}).items():
        if key in _CORRELATIONS and isinstance(value, str) and value:
            result[key] = value if _DIGEST.fullmatch(value) else correlation_id(value)
        elif key in _TEXT_ATTRIBUTES and isinstance(value, str) and _TOKEN.fullmatch(value):
            result[key] = value
        elif key in _NUMBER_ATTRIBUTES and type(value) is int and value >= 0:
            result[key] = value
        elif key == "_MS.sampleRate" and type(value) in {int, float} and 0 <= value <= 100:
            result[key] = value
        elif key == "http.route" and isinstance(value, str) and _ROUTE.fullmatch(value):
            result[key] = value
    return result


def _safe_name(span: Span, attributes: dict[str, Any]) -> str:
    if _NATIVE_NAME.fullmatch(span.name):
        return span.name
    method = attributes.get("http.request.method", attributes.get("http.method"))
    if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
        return f"{method} {attributes.get('http.route', '/')}"
    return "operation"


def _safe_resource(resource: Resource | None) -> Resource:
    resource = resource or Resource({})
    return Resource(
        {key: value for key, value in resource.attributes.items() if key in _RESOURCE_ATTRIBUTES},
        schema_url=resource.schema_url,
    )


def _safe_scope(scope: InstrumentationScope | None) -> InstrumentationScope | None:
    if scope is None:
        return None
    return InstrumentationScope(
        scope.name, scope.version, scope.schema_url, attributes=_safe_attributes(scope.attributes)
    )


def _safe_span_context(context: trace.SpanContext) -> trace.SpanContext:
    return trace.SpanContext(
        trace_id=context.trace_id,
        span_id=context.span_id,
        is_remote=context.is_remote,
        trace_flags=context.trace_flags,
    )


class SafetySpanProcessor(SpanProcessor):
    """Sanitize before *any* exporter, including pre-existing hosted processors."""

    def on_start(self, span: Span, parent_context: Any = None) -> None:
        span.set_attributes(current_log_context())

    def _on_ending(self, span: Span) -> None:
        # OTel 1.44's pre-export hook runs before every on_end processor. Public
        # APIs cannot delete attributes/events or change an ended span. Keep this
        # version-tested mutation seam here, not in framework/application code.
        attributes = _safe_attributes(span.attributes)
        span._name = _safe_name(span, attributes)
        span._attributes = attributes
        span._status = Status(span.status.status_code)
        span._events = [
            Event(event.name, _safe_attributes(event.attributes), event.timestamp)
            for event in span.events
            if event.name in _EVENT_NAMES
        ]
        span._links = [
            Link(_safe_span_context(link.context), _safe_attributes(link.attributes))
            for link in span.links
        ]
        span._context = _safe_span_context(span.context)
        span._resource = _safe_resource(span.resource)
        span._instrumentation_scope = _safe_scope(span.instrumentation_scope)


class SafetyLogProcessor(LogRecordProcessor):
    def on_emit(self, log_record: ReadWriteLogRecord) -> None:
        record = log_record.log_record
        attributes = safe_log_attributes(dict(record.attributes or {}))
        record.attributes = attributes
        record.body = attributes.get("event_type", "Operational event (details suppressed)")
        log_record.resource = _safe_resource(log_record.resource)
        log_record.instrumentation_scope = _safe_scope(log_record.instrumentation_scope)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 5000) -> bool:
        return True


@contextmanager
def telemetry_context(**values: Any):
    """Correlate separate commands without changing native MAF parentage."""
    with log_context(**values):
        current = trace.get_current_span()
        current.set_attributes(current_log_context())
        yield


def _metric_views() -> list[Any]:
    from opentelemetry.sdk.metrics.view import DropAggregation, View

    keys = (
        "gen_ai.operation.name",
        "gen_ai.provider.name",
        "gen_ai.system",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.token.type",
        "error.type",
        "http.request.method",
        "http.method",
        "http.response.status_code",
        "http.status_code",
    )
    return [
        View(instrument_name="*", aggregation=DropAggregation()),
        *[
            View(instrument_name=name, attribute_keys=keys)
            for name in (
                "gen_ai.client.operation.duration",
                "gen_ai.client.token.usage",
                "http.server.request.duration",
                "http.server.duration",
            )
        ],
    ]


@dataclass
class _ExportTask:
    done: ThreadEvent = field(default_factory=ThreadEvent)
    success: bool = False

    @classmethod
    def start(
        cls, operation: Callable[[], Any], *, after: _ExportTask | None = None
    ) -> _ExportTask:
        task = cls()

        def execute() -> None:
            if after is not None:
                after.done.wait()
            try:
                task.success = operation() is not False
            except Exception:
                task.success = False
            finally:
                task.done.set()

        Thread(target=execute, name="maf-telemetry-export", daemon=True).start()
        return task


def _wait_tasks(tasks: list[_ExportTask], timeout_millis: int) -> bool:
    deadline = monotonic() + max(0, timeout_millis) / 1000
    for task in tasks:
        task.done.wait(max(0, deadline - monotonic()))
    return all(task.done.is_set() and task.success for task in tasks)


def _instrument_fastapi(app: FastAPI, tracer_provider: Any, meter_provider: Any) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls="health/live,health/ready",
        # Empty lists fall back to capture-all environment settings in ASGI.
        http_capture_headers_server_request=["(?!)"],
        http_capture_headers_server_response=["(?!)"],
        http_capture_headers_sanitize_fields=[".*"],
        exclude_spans=["receive", "send"],
    )


def instrument_api_app(app: FastAPI, settings: Settings) -> None:
    """Prepare scoped middleware; proxy providers activate when lifespan configures export."""
    if settings.applicationinsights_connection_string or settings.otel_exporter_otlp_endpoint:
        _instrument_fastapi(app, trace.get_tracer_provider(), metrics.get_meter_provider())


@dataclass
class TelemetryHandle:
    mode: str
    _providers: tuple[Any, ...] = field(default=(), repr=False)
    _tracer_provider: Any = field(default=None, repr=False)
    _meter_provider: Any = field(default=None, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)
    _shutdown_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _flush_tasks: dict[int, _ExportTask] = field(default_factory=dict, init=False, repr=False)

    def instrument_app(self, app: FastAPI) -> None:
        """Call at app construction, before ASGI builds middleware; never at import."""
        if self.mode not in {"azure_monitor", "otlp"}:
            return
        _instrument_fastapi(app, self._tracer_provider, self._meter_provider)

    def force_flush(self, timeout_millis: int = 5000) -> bool:
        # SDK 1.44's BatchProcessor.force_flush ignores its timeout argument.
        # Bound the caller's wait as well; never concurrently flush the same provider.
        with self._shutdown_lock:
            if self._stopped:
                return False
            for index, provider in enumerate(self._providers):
                previous = self._flush_tasks.get(index)
                if previous is None or previous.done.is_set():
                    self._flush_tasks[index] = _ExportTask.start(
                        lambda owner=provider: owner.force_flush(timeout_millis=timeout_millis)
                    )
            return _wait_tasks(list(self._flush_tasks.values()), timeout_millis)

    def shutdown(self) -> None:
        """Only flush/close providers created here; platform ownership is untouched."""
        with self._shutdown_lock:
            if self._stopped or not self._providers:
                return
            if not self.force_flush(timeout_millis=_EXPORT_TIMEOUT_MILLIS):
                logger.warning(
                    "telemetry.flush_failed", extra={"event_type": "telemetry.flush_failed"}
                )
            self._stopped = True
            tasks = [
                _ExportTask.start(provider.shutdown, after=self._flush_tasks[index])
                for index, provider in enumerate(self._providers)
            ]
            if not _wait_tasks(tasks, _EXPORT_TIMEOUT_MILLIS):
                logger.warning(
                    "telemetry.shutdown_failed",
                    extra={"event_type": "telemetry.shutdown_failed"},
                )


def _resource(settings: Settings) -> Resource:
    return Resource(
        {
            "service.name": settings.otel_service_name or "model-to-harness-maf-api",
            "service.version": settings.otel_service_version or version("model-to-harness-maf"),
            "deployment.environment.name": settings.app_env,
        }
    )


def _otlp_endpoints(endpoint: str) -> dict[str, str]:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OTLP endpoint must be an HTTP(S) URL without credentials or query")
    base = parsed.path.rstrip("/")
    if base.endswith("/v1/traces"):
        base = base[: -len("/v1/traces")]
    return {
        signal: urlunsplit(parsed._replace(path=f"{base}/v1/{signal}"))
        for signal in ("traces", "logs", "metrics")
    }


def _configure_otlp(settings: Settings, processor: SafetySpanProcessor) -> TelemetryHandle:
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.logging.handler import LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoints = _otlp_endpoints(settings.otel_exporter_otlp_endpoint or "")
    resource = _resource(settings)
    tracer = TracerProvider(resource=resource, shutdown_on_exit=False)
    tracer.add_span_processor(processor)
    tracer.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoints["traces"], timeout=5))
    )
    logs = LoggerProvider(resource=resource, shutdown_on_exit=False)
    logs.add_log_record_processor(SafetyLogProcessor())
    logs.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoints["logs"], timeout=5))
    )
    meter = MeterProvider(
        resource=resource,
        shutdown_on_exit=False,
        views=_metric_views(),
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoints["metrics"], timeout=5),
                export_timeout_millis=5000,
            )
        ],
    )
    trace.set_tracer_provider(tracer)
    set_logger_provider(logs)
    metrics.set_meter_provider(meter)
    logging.getLogger("maf_double_charge").addHandler(LoggingHandler(logger_provider=logs))
    return TelemetryHandle("otlp", (meter, tracer, logs), tracer, meter)


def _configure_azure(settings: Settings, processor: SafetySpanProcessor) -> TelemetryHandle:
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(
        connection_string=settings.applicationinsights_connection_string,
        resource=_resource(settings),
        logger_name="maf_double_charge",
        instrumentation_options={name: {"enabled": False} for name in _INSTRUMENTATIONS},
        span_processors=[processor],
        log_record_processors=[SafetyLogProcessor()],
        views=_metric_views(),
        enable_live_metrics=False,
        enable_performance_counters=False,
        disable_offline_storage=True,
        timeout=5,
    )
    tracer = trace.get_tracer_provider()
    meter = metrics.get_meter_provider()
    logs = get_logger_provider()
    return TelemetryHandle("azure_monitor", (meter, tracer, logs), tracer, meter)


def apply_hosted_instrumentation_policy() -> None:
    """Honor HTTP opt-outs after the hosted distro's separate instrumentation pass."""
    disabled = {
        name.strip()
        for name in os.environ.get("OTEL_PYTHON_DISABLED_INSTRUMENTATIONS", "").split(",")
    } & {"httpx", "httpx2", "requests", "urllib", "urllib3"}
    if not disabled:
        return
    for entry in entry_points(group="opentelemetry_instrumentor"):
        if entry.name not in disabled:
            continue
        instrumentor = entry.load()()
        if instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.uninstrument()
            if instrumentor.is_instrumented_by_opentelemetry:
                raise RuntimeError(f"Hosted HTTP instrumentation opt-out failed: {entry.name}")


def configure_telemetry(settings: Settings, *, host: str = "api") -> TelemetryHandle:
    """Explicit process bootstrap; repeated identical calls share one lifecycle handle."""
    global _configured
    if host not in {"api", "hosted"}:
        raise ValueError("Telemetry host must be 'api' or 'hosted'")
    key = (
        host,
        settings.applicationinsights_connection_string,
        settings.otel_exporter_otlp_endpoint,
        settings.otel_service_name,
        settings.otel_service_version,
        settings.app_env,
    )
    with _lock:
        if _configured is not None:
            if _configured[0] != key or _configured[1]._stopped:
                raise RuntimeError("Telemetry is process-scoped; restart to change configuration")
            return _configured[1]
        if (
            host == "hosted"
            or settings.applicationinsights_connection_string
            or settings.otel_exporter_otlp_endpoint
        ) and not version("opentelemetry-sdk").startswith("1.44."):
            raise RuntimeError("Telemetry safety requires the tested OpenTelemetry SDK 1.44 family")
        from agent_framework.observability import OBSERVABILITY_SETTINGS, enable_instrumentation

        enable_instrumentation(enable_sensitive_data=False)
        OBSERVABILITY_SETTINGS.enable_sensitive_data = False
        OBSERVABILITY_SETTINGS.enable_message_events = False
        provider = trace.get_tracer_provider()
        processor = SafetySpanProcessor()
        if host == "hosted":
            if not isinstance(provider, TracerProvider):
                raise RuntimeError("Initialize the hosted platform tracer provider before MAF")
            provider.add_span_processor(processor)
            handle = TelemetryHandle("hosted", _tracer_provider=provider)
        elif not (
            settings.applicationinsights_connection_string or settings.otel_exporter_otlp_endpoint
        ):
            handle = TelemetryHandle("disabled")
        else:
            if not isinstance(provider, trace.ProxyTracerProvider):
                raise RuntimeError("API telemetry cannot replace an existing tracer provider")
            from opentelemetry.sdk.metrics import MeterProvider

            if isinstance(get_logger_provider(), LoggerProvider) or isinstance(
                metrics.get_meter_provider(), MeterProvider
            ):
                raise RuntimeError("API telemetry cannot replace existing log or metric providers")
            if (
                settings.applicationinsights_connection_string
                and settings.otel_exporter_otlp_endpoint
            ):
                raise ValueError("Select Application Insights or OTLP, not both")
            if os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true" or any(
                os.environ.get(f"OTEL_{signal}_EXPORTER", "").strip().lower() == "none"
                for signal in ("TRACES", "LOGS", "METRICS")
            ):
                raise ValueError("Configured export conflicts with OpenTelemetry disable flags")
            handle = (
                _configure_azure(settings, processor)
                if settings.applicationinsights_connection_string
                else _configure_otlp(settings, processor)
            )
        protect_log_handlers()
        _configured = (key, handle)
        return handle
