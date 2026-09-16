import os
from types import SimpleNamespace

import pytest
from model_to_harness_langgraph import bootstrap
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.infrastructure import telemetry
from opentelemetry import trace
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON


def test_dotenv_exporter_settings_are_passed_without_changing_process_environment(
    tmp_path, monkeypatch
):
    import azure.monitor.opentelemetry

    path = tmp_path / "settings.env"
    path.write_text(
        "APPLICATIONINSIGHTS_CONNECTION_STRING=fixture-connection\n"
        "OTEL_SERVICE_NAME=dotenv-service\nAPP_ENV=dotenv-environment\nTELEMETRY_ENABLED=true\n"
    )
    monkeypatch.delenv("TELEMETRY_ENABLED")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "process-service")
    settings = Settings(_env_file=path)
    previous, calls = object(), []
    active = [previous]
    provider = SimpleNamespace(
        sampler=ALWAYS_ON,
        force_flush=lambda: calls.append("flush"),
        shutdown=lambda: calls.append("shutdown"),
    )

    def configure(**kwargs):
        assert kwargs["connection_string"] == "fixture-connection"
        assert kwargs["resource"].attributes["service.name"] == "process-service"
        assert kwargs["resource"].attributes["deployment.environment"] == "dotenv-environment"
        assert kwargs["sampling_ratio"] == 1.0
        assert all(not option["enabled"] for option in kwargs["instrumentation_options"].values())
        active[0] = provider

    monkeypatch.setattr(trace, "get_tracer_provider", lambda: active[0])
    monkeypatch.setattr(azure.monitor.opentelemetry, "configure_azure_monitor", configure)
    environment = dict(os.environ)
    owned = telemetry.configure_telemetry(settings)
    assert owned.providers == (provider,)
    assert dict(os.environ) == environment
    owned.close()
    assert calls == ["flush", "shutdown"]


@pytest.mark.parametrize("field", [
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
    "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED",
])
@pytest.mark.parametrize("source", ["dotenv", "process-with-constructor-override"])
def test_capture_rejected_before_exporter_setup(tmp_path, monkeypatch, field, source):
    import azure.monitor.opentelemetry

    def forbidden(**kwargs):
        pytest.fail("Unsafe capture must fail before configuring exporters")

    monkeypatch.setattr(azure.monitor.opentelemetry, "configure_azure_monitor", forbidden)
    path = tmp_path / "settings.env"
    path.write_text(f"{field}=true\n")
    if source == "dotenv":
        settings = Settings(_env_file=path, telemetry_enabled=True)
    else:
        monkeypatch.setenv(field, "true")
        settings = Settings(_env_file=None, **{field.lower(): "false"})
    with pytest.raises(RuntimeError, match="capture"):
        telemetry.configure_telemetry(settings)


def test_explicit_off_never_configures_local_exporter(monkeypatch):
    import azure.monitor.opentelemetry

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "process-connection")
    monkeypatch.setattr(
        azure.monitor.opentelemetry, "configure_azure_monitor",
        lambda **kwargs: pytest.fail("Explicit telemetry off must not install providers"),
    )
    assert telemetry.configure_telemetry(
        Settings(_env_file=None, telemetry_enabled=False)
    ).providers == ()


def test_hosted_off_does_not_bypass_sampler_or_borrow_provider_ownership(monkeypatch):
    provider = SimpleNamespace(sampler=ALWAYS_OFF)
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(telemetry, "entry_points", lambda **kwargs: [])
    settings = Settings(_env_file=None, telemetry_enabled=False)
    with pytest.raises(RuntimeError, match="complete"):
        telemetry.configure_telemetry(settings, hosted=True)
    provider.sampler = ALWAYS_ON
    assert telemetry.configure_telemetry(settings, hosted=True).providers == ()


def test_dotenv_connection_still_requires_complete_actual_sampler(tmp_path, monkeypatch):
    path = tmp_path / "settings.env"
    path.write_text("APPLICATIONINSIGHTS_CONNECTION_STRING=fixture\n")
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: SimpleNamespace(sampler=ALWAYS_OFF))
    with pytest.raises(RuntimeError, match="complete"):
        telemetry.verify_telemetry_policy(Settings(_env_file=path, telemetry_enabled=True))


async def test_bootstrap_passes_the_exact_resolved_settings(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
    from model_to_harness_langgraph.testing.fakes import FakeDomainGateway, FakeModel

    settings = Settings(_env_file=None, telemetry_enabled=False)
    seen = []

    def configure(resolved, *, hosted):
        seen.append((resolved, hosted))
        return telemetry.Telemetry()

    monkeypatch.setattr(bootstrap, "configure_telemetry", configure)
    async with bootstrap.open_runtime(
        settings, audit=InMemoryAuditRepository(), checkpointer=InMemorySaver(),
        model=FakeModel(), gateway=FakeDomainGateway(),
    ):
        pass
    assert seen == [(settings, False)]
