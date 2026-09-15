import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from hashlib import sha256

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode


class SafeExporter(SpanExporter):
    """Export only fixed-name application spans, without content or exception events."""

    def __init__(self, delegate: SpanExporter) -> None:
        self.delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]):
        safe = [
            ReadableSpan(
                name=span.name,
                context=span.context,
                parent=span.parent,
                kind=span.kind,
                resource=Resource.create({"service.name": "checkout-recovery-maf-api"}),
                attributes={
                    k: v
                    for k, v in (span.attributes or {}).items()
                    if k in {"checkout.component", "checkout.correlation"}
                },
                status=Status(span.status.status_code),
                start_time=span.start_time,
                end_time=span.end_time,
            )
            for span in spans
            if span.name.startswith("checkout.")
        ]
        return self.delegate.export(safe)

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)


def configure_api_telemetry() -> TracerProvider | None:
    connection = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection:
        return None
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

    provider = TracerProvider(
        resource=Resource.create({"service.name": "checkout-recovery-maf-api"})
    )
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
