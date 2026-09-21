import ast
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/src/checkout_recovery_copilot"


def test_lane_has_no_maf_or_poc_runtime_dependency():
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert not any(
        requirement.startswith("agent-framework")
        for requirement in manifest["project"]["dependencies"]
    )
    forbidden = ("agent_framework", "checkout_recovery_maf", "maf_double_charge")
    for path in SOURCE.rglob("*.py"):
        text = path.read_text()
        assert "harness/.poc" not in text, path
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden), path
            elif isinstance(node, ast.Import):
                assert not any(alias.name.startswith(forbidden) for alias in node.names), path


def test_imports_do_not_create_apps_or_runtime_resources():
    code = """
from unittest.mock import patch
import fastapi
with (
    patch.object(fastapi, 'FastAPI', side_effect=AssertionError('app at import')),
    patch('psycopg_pool.ConnectionPool', side_effect=AssertionError('pool at import')),
    patch('azure.identity.aio.DefaultAzureCredential',
          side_effect=AssertionError('credential at import')),
):
    import checkout_recovery_copilot
    import checkout_recovery_copilot.bootstrap as bootstrap
    import checkout_recovery_copilot.main as main
    import checkout_recovery_copilot.projections
    assert not hasattr(bootstrap, 'app')
    assert not hasattr(main, 'app')
"""
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("CHECKOUT_COPILOT_")
    }
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr


def test_application_and_runtime_never_import_api_and_projections_are_pure():
    forbidden = {
        "application": ("checkout_recovery_copilot.api", "fastapi"),
        "projections": (
            "checkout_recovery_copilot.api",
            "checkout_recovery_copilot.infrastructure",
            "checkout_recovery_copilot.sdk",
            "fastapi",
            "psycopg",
        ),
    }
    for directory, prefixes in forbidden.items():
        for source in (SOURCE / directory).glob("*.py"):
            for node in ast.walk(ast.parse(source.read_text())):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith(prefixes), source
                elif isinstance(node, ast.Import):
                    assert not any(alias.name.startswith(prefixes) for alias in node.names), source
    for name in ("bootstrap.py", "config.py", "__init__.py"):
        text = (SOURCE / name).read_text()
        assert "checkout_recovery_copilot.api" not in text
        assert "fastapi" not in text
    assert not (SOURCE / "api/routes.py").exists()


def test_query_routes_only_use_service_safe_queries():
    source = ast.parse((SOURCE / "api/routers/cases.py").read_text())
    expected = {
        "get_case": "get_case_response",
        "list_events": "list_event_responses",
        "workspace_artifact": "get_workspace_artifact_response",
    }
    for node in source.body:
        if isinstance(node, ast.FunctionDef) and node.name in expected:
            service_calls = [
                call.func.attr
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "service"
            ]
            assert service_calls == [expected[node.name]]
            assert not any(
                isinstance(call, ast.Name) and call.id.startswith("project_")
                for call in ast.walk(node)
            )


def test_hosted_import_is_independent_of_api_and_runtime_initialization():
    code = """
import importlib.abc
import importlib.util
import sys
from types import ModuleType
from unittest.mock import Mock, patch

class BlockApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith('checkout_recovery_copilot.api'):
            raise AssertionError('Hosted imported the API')

sys.meta_path.insert(0, BlockApi())
sdk = ModuleType('azure.ai.agentserver.responses')
sdk.ResponsesAgentServerHost = Mock(side_effect=AssertionError('host at import'))
sdk.TextResponse = Mock()
sys.modules[sdk.__name__] = sdk
with (
    patch('psycopg_pool.ConnectionPool', side_effect=AssertionError('pool at import')),
    patch('checkout_recovery_copilot.bootstrap.configure_api_telemetry',
          side_effect=AssertionError('Hosted API telemetry')),
    patch('checkout_recovery_copilot.bootstrap.create_runtime',
          side_effect=AssertionError('runtime at import')),
):
    spec = importlib.util.spec_from_file_location('hosted_isolated', sys.argv[1])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module._runtime is None
assert not any(name.startswith('checkout_recovery_copilot.api') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "infra/foundry-hosted/agent/main.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
