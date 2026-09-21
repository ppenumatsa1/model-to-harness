import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from enum import Enum
from hashlib import sha256

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode

_APPLICATION_NAMES = frozenset(
    {
        "checkout.api",
        "checkout.start",
        "checkout.approval",
        "checkout.resume",
        "checkout.remediation",
        "checkout.verification",
        "checkout.harness",
        "checkout.model",
        "checkout.subagent",
        "checkout.tool.read_order",
        "checkout.tool.read_payment",
        "checkout.tool.read_inventory",
        "checkout.tool.read_logs",
    }
)
_NATIVE_NAMES = {
    "invoke_agent": "checkout.native.agent",
    "create_agent": "checkout.native.agent",
    "chat": "checkout.native.model",
    "embeddings": "checkout.native.model",
    "execute_tool": "checkout.native.tool",
}
_RESOURCE = Resource({"service.name": "checkout-recovery-maf-api"})


class _EnvironmentDefault(Enum):
    USE_ENVIRONMENT = "environment"


def _safe_context(context: SpanContext | None) -> SpanContext | None:
    if context is None:
        return None
    # Keep graph identity, not vendor-provided trace-state content.
    return SpanContext(
        trace_id=context.trace_id,
        span_id=context.span_id,
        is_remote=context.is_remote,
        trace_flags=context.trace_flags,
    )


def _safe_attributes(span: ReadableSpan) -> dict[str, str | int]:
    source = span.attributes or {}
    safe = {}
    method = source.get("http.request.method")
    if isinstance(method, str) and method in {
        "GET",
        "HEAD",
        "OPTIONS",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    }:
        safe["http.request.method"] = method
    status = source.get("http.response.status_code")
    if type(status) is int and 100 <= status <= 599:
        safe["http.response.status_code"] = status
    if source.get("checkout.component") == "maf":
        safe["checkout.component"] = "maf"
    correlation = source.get("checkout.correlation")
    if isinstance(correlation, str) and re.fullmatch(r"[0-9a-f]{24}", correlation):
        safe["checkout.correlation"] = correlation
    operation_name = source.get("gen_ai.operation.name")
    if isinstance(operation_name, str) and operation_name in _NATIVE_NAMES:
        safe["gen_ai.operation.name"] = operation_name
    return safe


def _safe_name(span: ReadableSpan) -> str:
    if span.name in _APPLICATION_NAMES:
        return span.name
    operation_name = (span.attributes or {}).get("gen_ai.operation.name")
    if isinstance(operation_name, str):
        return _NATIVE_NAMES.get(operation_name, "checkout.native.span")
    return "checkout.native.span"


class SafeExporter(SpanExporter):
    """Retain the native parent graph, exporting only fixed, content-free metadata."""

    def __init__(self, delegate: SpanExporter) -> None:
        self.delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]):
        safe = [
            ReadableSpan(
                name=_safe_name(span),
                context=_safe_context(span.context),
                parent=_safe_context(span.parent),
                kind=span.kind,
                resource=_RESOURCE,
                attributes=_safe_attributes(span),
                status=Status(span.status.status_code),
                start_time=span.start_time,
                end_time=span.end_time,
            )
            for span in spans
            if not (
                span.name == "checkout.api"
                and (span.attributes or {}).get("checkout.suppress_successful_read") is True
                and span.status.status_code is not StatusCode.ERROR
            )
        ]
        return self.delegate.export(safe) if safe else SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)


def configure_api_telemetry(
    connection_string: str | None | _EnvironmentDefault = _EnvironmentDefault.USE_ENVIRONMENT,
) -> TracerProvider | None:
    """Configure API traces only; explicit None disables setup regardless of the environment."""
    connection = (
        os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if connection_string is _EnvironmentDefault.USE_ENVIRONMENT
        else connection_string
    )
    if not connection:
        return None
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

    provider = TracerProvider(resource=_RESOURCE)
    provider.add_span_processor(
        BatchSpanProcessor(
            SafeExporter(
                AzureMonitorTraceExporter(
                    connection_string=connection, disable_offline_storage=True
                )
            )
        )
    )
    trace.set_tracer_provider(provider)
    return provider


def record_api_response(method: str, status_code: int) -> None:
    span = trace.get_current_span()
    span.set_attribute("http.request.method", method)
    span.set_attribute("http.response.status_code", status_code)
    if status_code >= 400:
        span.set_status(Status(StatusCode.ERROR))
    elif method in {"GET", "HEAD", "OPTIONS"} and 200 <= status_code < 400:
        span.set_attribute("checkout.suppress_successful_read", True)


@contextmanager
def operation(name: str, case_id: str | None = None) -> Iterator[None]:
    attributes = {"checkout.component": "maf"}
    if case_id:
        attributes["checkout.correlation"] = sha256(case_id.encode()).hexdigest()[:24]
    with trace.get_tracer("checkout_recovery").start_as_current_span(
        f"checkout.{name}",
        attributes=attributes,
        kind=SpanKind.SERVER if name == "api" else SpanKind.INTERNAL,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield
        except BaseException:
            span.set_status(Status(StatusCode.ERROR))
            raise
