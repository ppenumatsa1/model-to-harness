import os
import sys
from pathlib import Path

import pytest
from checkout_recovery_copilot.config import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


@pytest.fixture(autouse=True)
def isolated_process_settings(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for key in os.environ:
        if key.startswith(("CHECKOUT_COPILOT_", "OTEL_")) or key in {
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
        }:
            monkeypatch.delenv(key, raising=False)
