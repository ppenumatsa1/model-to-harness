import os
import runpy
from unittest.mock import Mock

import pytest
from checkout_recovery_copilot.config import Settings, checkout_env_file
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    for key in os.environ:
        if key.upper().startswith("CHECKOUT_COPILOT_") or key.upper() == (
            "APPLICATIONINSIGHTS_CONNECTION_STRING"
        ):
            monkeypatch.delenv(key)
    monkeypatch.setitem(Settings.model_config, "env_file", tmp_path / "absent.env")


def test_scripted_loopback_defaults():
    settings = Settings(_env_file=None)
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8030
    assert settings.frontend_origin == "http://127.0.0.1:5180"
    assert settings.environment == "development"
    assert settings.execution_mode == "scripted"
    assert settings.applicationinsights_connection_string is None
    settings.validate_runtime()


def test_empty_optional_trace_file_does_not_select_current_directory():
    assert Settings(_env_file=None, trace_file="").trace_file is None


def test_production_rejects_local_trace_file():
    settings = Settings(_env_file=None, environment="production", trace_file="receipt.jsonl")
    with pytest.raises(ValueError, match="local trace files"):
        settings.validate_runtime()


def test_only_editable_lane_is_discovered(tmp_path, monkeypatch):
    lane = tmp_path / "harness/checkout-recovery/copilot-sdk"
    module = lane / "backend/src/checkout_recovery_copilot/config.py"
    module.parent.mkdir(parents=True)
    (lane / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert checkout_env_file(module) == lane / ".env"
    for other in (
        tmp_path / "site-packages/checkout_recovery_copilot/config.py",
        lane / "infra/foundry-hosted/agent/checkout_recovery_copilot/config.py",
        tmp_path / "other/maf/backend/src/checkout_recovery_copilot/config.py",
    ):
        assert checkout_env_file(other) is None
    (lane / "pyproject.toml").unlink()
    assert checkout_env_file(module) is None


def test_settings_precedence_and_telemetry_alias(tmp_path, monkeypatch):
    env_file = tmp_path / "selected.env"
    env_file.write_text(
        "CHECKOUT_COPILOT_API_PORT=8001\n"
        "CHECKOUT_COPILOT_DATABASE_URL=synthetic-dotenv-database\n"
        "APPLICATIONINSIGHTS_CONNECTION_STRING=synthetic-dotenv-telemetry\n"
        "UNRELATED_SECRET=synthetic-unrelated\n",
        encoding="utf-8",
    )
    from_file = Settings(_env_file=env_file)
    assert from_file.api_port == 8001
    assert from_file.database_url == "synthetic-dotenv-database"
    assert from_file.applicationinsights_connection_string == "synthetic-dotenv-telemetry"
    monkeypatch.setenv("CHECKOUT_COPILOT_API_PORT", "18020")
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "synthetic-process-telemetry")
    from_process = Settings(_env_file=env_file)
    assert from_process.api_port == 18020
    assert from_process.applicationinsights_connection_string == "synthetic-process-telemetry"
    explicit = Settings(
        _env_file=env_file,
        api_port=8123,
        applicationinsights_connection_string="synthetic-explicit-telemetry",
    )
    assert explicit.api_port == 8123
    assert explicit.applicationinsights_connection_string == "synthetic-explicit-telemetry"
    assert "synthetic-explicit-telemetry" not in repr(explicit)
    assert "UNRELATED_SECRET" not in explicit.model_dump()


def test_none_disables_dotenv_but_preserves_process_settings(tmp_path, monkeypatch):
    env_file = tmp_path / "selected.env"
    env_file.write_text("CHECKOUT_COPILOT_API_PORT=8001\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env_file)
    assert Settings().api_port == 8001
    assert Settings(_env_file=None).api_port == 8030
    monkeypatch.setenv("CHECKOUT_COPILOT_API_PORT", "18020")
    assert Settings(_env_file=None).api_port == 18020


def test_cwd_and_other_dotenv_files_are_not_searched(tmp_path, monkeypatch):
    selected = tmp_path / "lane.env"
    selected.write_text("CHECKOUT_COPILOT_API_PORT=18020\n", encoding="utf-8")
    cwd = tmp_path / "unrelated"
    cwd.mkdir()
    for name in (".env", ".env.local", ".env.production", ".env.compose"):
        (cwd / name).write_text("CHECKOUT_COPILOT_API_PORT=9000\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    monkeypatch.setitem(Settings.model_config, "env_file", selected)
    assert Settings().api_port == 18020
    assert Settings(_env_file=None).api_port == 8030


@pytest.mark.parametrize("port", [0, 65536, -1, "not-a-port", 1.5])
def test_api_port_bounds(port):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_port=port)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "0.0.0.0", "::", "::1", "api.local"])
def test_valid_api_hosts(host):
    assert Settings(_env_file=None, api_host=host).api_host == host


@pytest.mark.parametrize("host", ["", "http://localhost", "localhost:8030", "bad/name", "bad host"])
def test_invalid_api_hosts(host):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_host=host)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "file:///etc/passwd",
        "https://user:secret@example.com",
        "http://localhost:15175/path",
        "http://localhost:15175?query",
        "http://localhost:15175#fragment",
        "http://localhost:65536",
        "http://localhost:0",
        "http://localhost:15175\\evil",
    ],
)
def test_invalid_frontend_origins(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, frontend_origin=origin)


def test_frontend_origin_override(monkeypatch):
    monkeypatch.setenv("CHECKOUT_COPILOT_FRONTEND_ORIGIN", "http://127.0.0.1:15175/")
    assert Settings(_env_file=None).frontend_origin == "http://127.0.0.1:15175"
    assert Settings(_env_file=None, frontend_origin="https://example.com").frontend_origin == (
        "https://example.com"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"database_url": "synthetic-db"},
        {"database_url": "synthetic-db", "api_token": "synthetic-token"},
        {
            "database_url": "synthetic-db",
            "api_token": "synthetic-token",
            "execution_mode": "copilot",
        },
    ],
)
def test_production_still_fails_closed(overrides):
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production", **overrides).validate_runtime()


def test_valid_production_and_hosted_configuration():
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="synthetic-db",
        api_token="synthetic-token",
        execution_mode="copilot",
        foundry_project_endpoint="https://example.com",
        foundry_model_deployment="synthetic-model",
    )
    settings.validate_runtime()
    settings.validate_runtime(host="hosted")
    with pytest.raises(ValueError):
        Settings(_env_file=None).validate_runtime(host="hosted")


def test_launcher_passes_one_selected_settings_snapshot(monkeypatch):
    from checkout_recovery_copilot import main

    settings = Settings(_env_file=None, api_host="localhost", api_port=18020)
    app = object()
    factory = Mock(return_value=app)
    run = Mock()
    monkeypatch.setattr(main, "create_app", factory)
    monkeypatch.setattr("uvicorn.run", run)
    main.main(settings)
    factory.assert_called_once_with(settings=settings)
    run.assert_called_once_with(app, host="localhost", port=18020)


def test_module_launcher_selects_settings_once(monkeypatch):
    from checkout_recovery_copilot import main

    settings = Settings(_env_file=None, api_port=18020)
    select = Mock(return_value=settings)
    factory = Mock(return_value=object())
    run = Mock()
    monkeypatch.setattr(main, "Settings", select)
    monkeypatch.setattr(main, "create_app", factory)
    monkeypatch.setattr("uvicorn.run", run)
    runpy.run_module("checkout_recovery_copilot", run_name="__main__")
    select.assert_called_once_with()
    factory.assert_called_once_with(settings=settings)
    assert run.call_args.kwargs["port"] == 18020


def test_invalid_production_never_starts_server(monkeypatch):
    from checkout_recovery_copilot import main

    factory = Mock()
    run = Mock()
    monkeypatch.setattr(main, "create_app", factory)
    monkeypatch.setattr("uvicorn.run", run)
    with pytest.raises(ValueError):
        main.main(Settings(_env_file=None, environment="production"))
    factory.assert_not_called()
    run.assert_not_called()
