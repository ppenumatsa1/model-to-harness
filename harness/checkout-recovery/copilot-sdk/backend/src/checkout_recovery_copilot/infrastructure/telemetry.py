import json
import logging
import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from enum import Enum
from hashlib import sha256
from pathlib import Path

from model_to_harness_shared.fixtures.checkout import CHECKOUT_SCENARIO_FIXTURES
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
        "checkout.tool.write_plan",
        "checkout.tool.read_plan",
        "checkout.tool.delegate_inventory",
    }
)
_NATIVE_NAMES = {
    "invoke_agent": "checkout.native.agent",
    "create_agent": "checkout.native.agent",
    "chat": "checkout.native.model",
    "embeddings": "checkout.native.model",
    "execute_tool": "checkout.native.tool",
}
_RESOURCE = Resource({"service.name": "checkout-recovery-copilot-api"})
_FIXTURE_PAYLOADS: dict[str, set[str]] = {
    "read_order": set(),
    "read_payment": set(),
    "read_inventory": set(),
}
for _fixture in CHECKOUT_SCENARIO_FIXTURES.values():
    for _tool, _result in (
        ("read_order", {"status": _fixture.order.status.value}),
        (
            "read_payment",
            {
                "status": _fixture.payment_attempt.status.value,
                "amount_minor": _fixture.payment_attempt.amount_minor,
            },
        ),
        (
            "read_inventory",
            {
                "status": _fixture.reservation.status.value,
                "quantity": _fixture.reservation.quantity,
            },
        ),
    ):
        _FIXTURE_PAYLOADS[_tool].add(json.dumps(_result, sort_keys=True, separators=(",", ":")))


def record_fixture_diagnostic(span, tool_name: str, result: dict) -> None:
    """Call only under the explicit capture flag; accept exact synthetic diagnostic shapes."""
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if encoded not in _FIXTURE_PAYLOADS.get(tool_name, ()):
        logging.getLogger(__name__).warning("Omitted non-allowlisted diagnostic trace content")
        return
    span.set_attribute("checkout.fixture_content", True)
    span.set_attribute("gen_ai.tool.name", tool_name)
    span.set_attribute("gen_ai.tool.call.arguments", "{}")
    span.set_attribute("gen_ai.tool.call.result", encoded)


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


def _safe_attributes(span: ReadableSpan) -> dict[str, str | bool | int]:
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
    if source.get("checkout.component") == "copilot":
        safe["checkout.component"] = "copilot"
    correlation = source.get("checkout.correlation")
    if isinstance(correlation, str) and re.fullmatch(r"[0-9a-f]{24}", correlation):
        safe["checkout.correlation"] = correlation
    operation_name = source.get("gen_ai.operation.name")
    if isinstance(operation_name, str) and operation_name in _NATIVE_NAMES:
        safe["gen_ai.operation.name"] = operation_name
    tool = source.get("gen_ai.tool.name")
    payload = source.get("gen_ai.tool.call.result")
    if (
        source.get("checkout.fixture_content") is True
        and isinstance(tool, str)
        and isinstance(payload, str)
        and payload in _FIXTURE_PAYLOADS.get(tool, ())
        and source.get("gen_ai.tool.call.arguments") == "{}"
    ):
        safe.update(
            {
                "checkout.fixture_content": True,
                "gen_ai.tool.name": tool,
                "gen_ai.tool.call.arguments": "{}",
                "gen_ai.tool.call.result": payload,
            }
        )
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


class LocalSpanExporter(SpanExporter):
    def __init__(self, path: Path) -> None:
        self.path = path

    def export(self, spans: Sequence[ReadableSpan]):
        from .copilot_telemetry import save_spans

        try:
            save_spans(self.path, list(spans))
        except OSError as error:
            logging.getLogger(__name__).error(
                "Local application trace receipt failed (%s)", type(error).__name__
            )
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS


def configure_api_telemetry(
    connection_string: str | None | _EnvironmentDefault = _EnvironmentDefault.USE_ENVIRONMENT,
    *,
    trace_file: Path | None = None,
) -> TracerProvider | None:
    """Configure API traces only; explicit None disables setup regardless of the environment."""
    connection = (
        os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if connection_string is _EnvironmentDefault.USE_ENVIRONMENT
        else connection_string
    )
    if not connection and trace_file is None:
        return None
    provider = TracerProvider(resource=_RESOURCE)
    if connection:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

        provider.add_span_processor(
            BatchSpanProcessor(
                SafeExporter(
                    AzureMonitorTraceExporter(
                        connection_string=connection, disable_offline_storage=True
                    )
                )
            )
        )
    if trace_file is not None:
        provider.add_span_processor(
            BatchSpanProcessor(
                SafeExporter(
                    LocalSpanExporter(trace_file.with_name(trace_file.name + ".application.jsonl"))
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
    attributes = {"checkout.component": "copilot"}
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
