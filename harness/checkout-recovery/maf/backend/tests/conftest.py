import os

import pytest
from checkout_recovery_maf.config import Settings


@pytest.fixture(autouse=True)
def isolated_process_settings(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for key in os.environ:
        if key.startswith(("CHECKOUT_RECOVERY_", "OTEL_")) or key in {
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
        }:
            monkeypatch.delenv(key, raising=False)
