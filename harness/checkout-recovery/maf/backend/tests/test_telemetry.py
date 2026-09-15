from checkout_recovery_maf.infrastructure.telemetry import SafeExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode


class RecordingExporter(SpanExporter):
    def export(self, spans):
        self.spans = spans
        return SpanExportResult.SUCCESS


def test_exporter_drops_sdk_content_and_exception_details():
    collector = RecordingExporter()
    exporter = SafeExporter(collector)
    exporter.export(
        [
            ReadableSpan(
                name="checkout.model",
                attributes={
                    "checkout.component": "maf",
                    "checkout.correlation": "hashed-case",
                    "gen_ai.input.messages": "private prompt",
                    "db.connection_string": "private credential",
                },
                resource=Resource({"service.name": "checkout", "secret": "private credential"}),
                status=Status(StatusCode.ERROR, "private prompt"),
            ),
            ReadableSpan(name="gen_ai.private prompt"),
        ]
    )
    assert len(collector.spans) == 1
    span = collector.spans[0]
    assert span.attributes == {"checkout.component": "maf", "checkout.correlation": "hashed-case"}
    assert span.status.description is None
    assert span.events == ()
    assert "secret" not in span.resource.attributes
