from __future__ import annotations

import runpy
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from maf_double_charge import config, main
from maf_double_charge.bootstrap import create_runtime
from maf_double_charge.config import Settings, checkout_env_file
from maf_double_charge.infrastructure.persistence import migrations
from maf_double_charge.testing.app import create_test_app
from maf_double_charge.testing.checkpoints import InMemoryRunCheckpointStorage
from maf_double_charge.testing.model import FakeModelClient
from maf_double_charge.testing.repository import InMemoryRepository


def test_checkout_selection_and_cwd_isolation(tmp_path, monkeypatch):
    lane = tmp_path / "maf"
    source = lane / "backend/src/maf_double_charge/config.py"
    source.parent.mkdir(parents=True)
    (lane / "pyproject.toml").write_text('[project]\nname = "model-to-harness-maf"\n')
    (lane / ".env").write_text("PORT=8123\nDATABASE_SCHEMA=maf_config_test\n")
    other = tmp_path / "langgraph"
    other.mkdir()
    (other / ".env").write_text("PORT=8999\nDATABASE_SCHEMA=wrong_lane\n")
    (tmp_path / ".env").write_text("PORT=8888\n")
    (lane / "backend/.env").write_text("PORT=8777\n")
    selected = checkout_env_file(source)
    assert selected == lane / ".env"
    monkeypatch.setitem(Settings.model_config, "env_file", selected)
    for cwd in [other, tmp_path, lane / "backend", lane]:
        monkeypatch.chdir(cwd)
        settings = Settings()
        assert settings.port == 8123
        assert settings.database_schema == "maf_config_test"


@pytest.mark.parametrize(
    "relative",
    [
        "venv/lib/python3.12/site-packages/maf_double_charge/config.py",
        "hosted/maf_double_charge/config.py",
        "maf/config.py",
        "langgraph/backend/src/maf_double_charge/config.py",
    ],
)
def test_installed_and_hosted_do_not_guess_dotenv(tmp_path, relative, monkeypatch):
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    (tmp_path / ".env").write_text("PORT=8999\n")
    assert checkout_env_file(source) is None
    source.write_text(Path(config.__file__).read_text())
    monkeypatch.chdir(tmp_path)
    installed = runpy.run_path(str(source))["Settings"]
    assert installed.model_config["env_file"] is None
    assert installed().port == 8010
    monkeypatch.setenv("PORT", "8123")
    assert installed().port == 8123


def test_real_editable_source_selects_only_lane_root():
    source = Path(config.__file__).resolve()
    assert checkout_env_file(source) == source.parents[3] / ".env"


def test_precedence_and_explicit_file_overrides(tmp_path, monkeypatch):
    default = tmp_path / "default.env"
    default.write_text("PORT=8123\nHOST=localhost\nMAX_TOOL_ATTEMPTS=4\n")
    alternate = tmp_path / "alternate.env"
    alternate.write_text("PORT=8234\n")
    monkeypatch.setitem(Settings.model_config, "env_file", default)
    assert Settings().port == 8123
    assert Settings(_env_file=alternate).port == 8234
    assert Settings(_env_file=None).port == 8010
    monkeypatch.setenv("PORT", "8345")
    assert Settings().port == 8345
    assert Settings(_env_file=alternate).port == 8345
    assert Settings(_env_file=None).port == 8345
    assert Settings(port=8456).port == 8456
    assert Settings().max_tool_attempts == 4


def test_safe_defaults_and_missing_storage_fail_before_model_creation(monkeypatch):
    settings = Settings(_env_file=None)
    assert settings.database_url == ""
    assert settings.frontend_origin == "http://localhost:5174"
    assert (settings.host, settings.port, settings.max_tool_attempts) == ("127.0.0.1", 8010, 3)
    model_constructor = Mock(side_effect=AssertionError("must not construct model"))
    monkeypatch.setattr("maf_double_charge.bootstrap.FoundryModelClient", model_constructor)
    for database_url in ["", "  "]:
        with pytest.raises(ValueError, match="DATABASE_URL is required"):
            create_runtime(Settings(_env_file=None, database_url=database_url))
    model_constructor.assert_not_called()


def test_missing_model_is_explicit_with_injected_storage():
    with pytest.raises(RuntimeError, match="FOUNDRY_PROJECT_ENDPOINT"):
        create_runtime(
            Settings(_env_file=None),
            repository=InMemoryRepository(),
            checkpoint_storage_factory=InMemoryRunCheckpointStorage,
        )


async def test_fully_injected_runtime_needs_no_real_settings():
    runtime = create_runtime(
        Settings(_env_file=None),
        repository=InMemoryRepository(),
        model=FakeModelClient(),
        checkpoint_storage_factory=InMemoryRunCheckpointStorage,
    )
    await runtime.start()
    await runtime.close()


async def test_fake_factory_and_evaluation_ignore_dotenv(tmp_path, monkeypatch):
    from maf_double_charge.evaluation import evaluate

    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "PORT=not-an-integer\n"
        "DATABASE_URL=private-database-sentinel\n"
        "FOUNDRY_PROJECT_ENDPOINT=https://invalid.example\n"
        "APPLICATIONINSIGHTS_CONNECTION_STRING=private-export-sentinel\n"
        "OTEL_EXPORTER_OTLP_ENDPOINT=https://invalid.example\n"
    )
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv)
    app = create_test_app()
    async with app.router.lifespan_context(app):
        pass
    assert all(result.passed for result in await evaluate())


def test_missing_database_migration_cli_fails_without_running_sql(monkeypatch, capsys):
    apply = Mock(side_effect=AssertionError("must not run SQL"))
    monkeypatch.setattr(migrations, "apply_migrations", apply)
    with pytest.raises(SystemExit) as caught:
        migrations.main([])
    assert caught.value.code == 1
    assert "DATABASE_URL is required" in capsys.readouterr().err
    apply.assert_not_called()


def test_main_uses_canonical_host_port(monkeypatch):
    monkeypatch.setenv("HOST", "127.0.0.2")
    monkeypatch.setenv("PORT", "8129")
    monkeypatch.setenv("APP_ENV", "test")
    run = Mock()
    monkeypatch.setattr(main.uvicorn, "run", run)
    main.run()
    run.assert_called_once_with(
        "maf_double_charge.api.app:create_app",
        factory=True,
        host="127.0.0.2",
        port=8129,
        reload=False,
    )


def test_launcher_resolves_its_venv_from_another_cwd(tmp_path):
    lane = tmp_path / "maf"
    scripts = lane / "scripts"
    scripts.mkdir(parents=True)
    original = Path(config.__file__).resolve().parents[3] / "scripts/dev-backend.sh"
    launcher = scripts / "dev-backend.sh"
    launcher.write_text(original.read_text())
    python = lane / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@"\n')
    python.chmod(0o755)
    result = subprocess.run(
        ["bash", str(launcher)], cwd=tmp_path, text=True, capture_output=True, check=True
    )
    assert result.stdout.splitlines() == [str(lane), "-m", "maf_double_charge.main"]
