import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph import bootstrap, config, main
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.infrastructure.persistence import migrations
from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
from model_to_harness_langgraph.testing.fakes import FakeDomainGateway, FakeModel
from pydantic import ValidationError

LANE = Path(__file__).resolve().parents[3]


def checkout(tmp_path):
    lane = tmp_path / "langgraph"
    package = lane / "backend/src/model_to_harness_langgraph"
    package.mkdir(parents=True)
    (lane / "pyproject.toml").touch()
    return lane, package


def test_dotenv_precedence_cwd_and_explicit_overrides(tmp_path, monkeypatch):
    lane, package = checkout(tmp_path)
    selected = config.checkout_env_file(package / "config.py")
    assert selected == lane / ".env"
    selected.write_text("PORT=8123\nAPP_ENV=lane\nDATABASE_URL=fixture-only\n")
    (tmp_path / ".env").write_text("PORT=9999\nAPP_ENV=wrong-root\n")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / ".env").write_text("PORT=9998\n")
    monkeypatch.setitem(Settings.model_config, "env_file", selected)
    monkeypatch.chdir(unrelated)
    assert Settings().port == 8123
    assert Settings().app_env == "lane"
    monkeypatch.setenv("PORT", "8124")
    assert Settings().port == 8124
    assert Settings(port=8125).port == 8125
    assert Settings(_env_file=None).database_url == ""
    alternate = tmp_path / "explicit.env"
    alternate.write_text("APP_ENV=explicit\n")
    assert Settings(_env_file=alternate).app_env == "explicit"
    assert "fixture-only" not in repr(Settings())


def test_no_root_neighbor_or_installed_package_fallback(tmp_path, monkeypatch):
    lane, package = checkout(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_URL=wrong-root\n")
    neighbor = tmp_path / "maf"
    neighbor.mkdir()
    (neighbor / ".env").write_text("DATABASE_URL=wrong-neighbor\n")
    monkeypatch.chdir(neighbor)
    monkeypatch.setitem(
        Settings.model_config, "env_file", config.checkout_env_file(package / "config.py")
    )
    assert Settings().database_url == ""
    for installed in (
        tmp_path / "site-packages/model_to_harness_langgraph/config.py",
        tmp_path / "hosted/model_to_harness_langgraph/config.py",
        Path("/model_to_harness_langgraph/config.py"),
    ):
        assert config.checkout_env_file(installed) is None
    assert config.checkout_env_file() == LANE / ".env"


def test_safe_defaults_and_origin_list():
    settings = Settings(_env_file=None, telemetry_enabled=False)
    assert (settings.host, settings.port) == ("127.0.0.1", 8000)
    assert settings.database_url == ""
    assert not settings.model_ready
    assert settings.allowed_origins == ["http://localhost:5173"]
    configured = Settings(_env_file=None, cors_origins=" http://localhost:5200, ,https://ui.test ")
    assert configured.allowed_origins == ["http://localhost:5200", "https://ui.test"]


def test_nondefault_frontend_origin_reaches_cors_middleware():
    from fastapi.testclient import TestClient
    from model_to_harness_langgraph.api.app import create_app

    app = create_app(
        settings=Settings(
            _env_file=None, telemetry_enabled=False,
            cors_origins="http://localhost:5201", port=8101,
        ),
        audit=InMemoryAuditRepository(), checkpointer=InMemorySaver(),
        model=FakeModel(), gateway=FakeDomainGateway(),
    )
    with TestClient(app) as client:
        response = client.options("/api/cases", headers={
            "Origin": "http://localhost:5201", "Access-Control-Request-Method": "POST",
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5201"
        response = client.options("/api/cases", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        })
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("port", [0, 65536, -1, "not-a-port"])
def test_invalid_ports_fail(port):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, port=port)


@pytest.mark.parametrize("verify_only", [False, True])
async def test_missing_storage_fails_before_setup_connection(monkeypatch, verify_only):
    async def forbidden(*args, **kwargs):
        pytest.fail("Missing configuration must not open a database connection")

    monkeypatch.setattr(migrations.AsyncConnection, "connect", forbidden)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        await migrations.setup_storage(
            Settings(_env_file=None, database_url="", telemetry_enabled=False),
            verify_only=verify_only,
        )


@pytest.mark.parametrize(
    ("values", "message"),
    [({}, "DATABASE_URL"), ({"database_url": "unused"}, "AZURE_OPENAI_ENDPOINT")],
)
async def test_missing_runtime_configuration_fails_before_telemetry_or_storage(
    monkeypatch, values, message
):
    def forbidden(*args, **kwargs):
        pytest.fail("Missing runtime configuration must fail before any external setup")

    monkeypatch.setattr(bootstrap, "configure_telemetry", forbidden)
    monkeypatch.setattr(bootstrap, "setup_storage", forbidden)
    with pytest.raises(RuntimeError, match=message):
        async with bootstrap.open_runtime(
            Settings(_env_file=None, telemetry_enabled=False, **values)
        ):
            pytest.fail("Incomplete real runtime must not start")


async def test_all_fake_injection_needs_no_real_configuration():
    async with bootstrap.open_runtime(
        Settings(_env_file=None, telemetry_enabled=False),
        audit=InMemoryAuditRepository(), checkpointer=InMemorySaver(),
        model=FakeModel(), gateway=FakeDomainGateway(),
    ) as runtime:
        await runtime.verify()


def test_main_uses_resolved_bind_settings(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main, "get_settings",
        lambda: Settings(_env_file=None, host="0.0.0.0", port=8126, telemetry_enabled=False),
    )
    monkeypatch.setattr(main.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    main.main()
    assert calls == [(("model_to_harness_langgraph.api.app:create_app",), {
        "factory": True, "host": "0.0.0.0", "port": 8126, "reload": True, "access_log": False,
    })]


def test_checkout_launcher_outside_cwd_uses_lane_venv_and_dotenv(tmp_path):
    lane, package = checkout(tmp_path)
    for name in ("config.py", "main.py"):
        shutil.copyfile(LANE / "backend/src/model_to_harness_langgraph" / name, package / name)
    (package / "__init__.py").touch()
    scripts = lane / "scripts"
    scripts.mkdir()
    shutil.copyfile(LANE / "scripts/dev-backend.sh", scripts / "dev-backend.sh")
    binary = lane / ".venv/bin"
    binary.mkdir(parents=True)
    (binary / "python").symlink_to(sys.executable)
    (lane / ".env").write_text("HOST=0.0.0.0\nPORT=8130\n")
    (tmp_path / ".env").write_text("PORT=9999\n")
    stub = tmp_path / "stub"
    stub.mkdir()
    (stub / "uvicorn.py").write_text(
        "import json\n"
        "def run(*args, **kwargs):\n"
        "    print(json.dumps({'host': kwargs['host'], 'port': kwargs['port']}))\n"
    )
    environment = {**os.environ, "PYTHONPATH": str(stub), "TELEMETRY_ENABLED": "false"}
    command = ["bash", str(scripts / "dev-backend.sh")]
    output = subprocess.check_output(command, cwd=tmp_path, env=environment, text=True)
    assert json.loads(output) == {"host": "0.0.0.0", "port": 8130}
    environment["PORT"] = "8131"
    output = subprocess.check_output(command, cwd=tmp_path, env=environment, text=True)
    assert json.loads(output)["port"] == 8131
