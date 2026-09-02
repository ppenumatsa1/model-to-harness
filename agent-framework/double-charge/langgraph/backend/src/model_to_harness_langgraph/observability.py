import logging
import os

logger = logging.getLogger(__name__)
_TELEMETRY_INTERNAL_LOGGERS = (
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.monitor.opentelemetry.exporter",
)


def configure_optional_azure_monitor() -> bool:
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.info("Azure Monitor tracing disabled; no connection string configured")
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        logger.warning("Install the observability extra to enable Azure Monitor tracing")
        return False
    configure_azure_monitor(connection_string=connection_string)
    # Exporter transport logs must not be exported by the logging pipeline itself.
    for logger_name in _TELEMETRY_INTERNAL_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    return True
