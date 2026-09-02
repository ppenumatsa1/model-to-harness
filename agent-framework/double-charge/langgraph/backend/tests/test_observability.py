import logging
import sys
from types import ModuleType

from model_to_harness_langgraph.observability import configure_optional_azure_monitor


def test_azure_monitor_suppresses_exporter_transport_logging(monkeypatch):
    calls: list[str] = []
    package = ModuleType("azure.monitor.opentelemetry")
    package.configure_azure_monitor = lambda *, connection_string: calls.append(
        connection_string
    )
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", package)
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test")

    transport = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
    exporter = logging.getLogger("azure.monitor.opentelemetry.exporter")
    previous_levels = transport.level, exporter.level
    try:
        transport.setLevel(logging.INFO)
        exporter.setLevel(logging.INFO)

        assert configure_optional_azure_monitor() is True

        assert calls == ["InstrumentationKey=test"]
        assert transport.level == logging.WARNING
        assert exporter.level == logging.WARNING
    finally:
        transport.setLevel(previous_levels[0])
        exporter.setLevel(previous_levels[1])
