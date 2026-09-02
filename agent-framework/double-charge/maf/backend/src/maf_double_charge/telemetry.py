from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .config import Settings

logger = logging.getLogger(__name__)


def configure_telemetry(settings: Settings) -> None:
    resource = Resource.create(
        {"service.name": "model-to-harness-maf", "deployment.environment": settings.app_env}
    )
    provider = TracerProvider(resource=resource)
    endpoint = settings.otel_exporter_otlp_endpoint
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        logger.info("OTLP trace export enabled")
    else:
        logger.info("Trace provider configured without exporter")
    trace.set_tracer_provider(provider)

