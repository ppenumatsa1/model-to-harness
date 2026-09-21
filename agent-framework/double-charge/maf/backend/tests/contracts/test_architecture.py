from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import maf_double_charge
import pytest


def package_root() -> Path:
    return Path(maf_double_charge.__file__).resolve().parent


def test_application_imports_only_its_ports_and_framework_neutral_domain() -> None:
    forbidden = {
        "agent_framework",
        "azure",
        "fastapi",
        "psycopg",
        "psycopg_pool",
        "maf_double_charge.api",
        "maf_double_charge.maf",
        "maf_double_charge.infrastructure",
        "maf_double_charge.testing",
    }
    violations = []
    for source in (package_root() / "application").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [
                    importlib.util.resolve_name(
                        "." * node.level + (node.module or ""), "maf_double_charge.application"
                    )
                    if node.level
                    else node.module or ""
                ]
            else:
                continue
            violations.extend(
                f"{source.name}:{node.lineno}: {name}"
                for name in imports
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
            )
    assert violations == []


def test_superseded_flat_modules_are_absent() -> None:
    for name in (
        "models",
        "orchestrator",
        "workflow",
        "repository",
        "checkpoints",
        "model_client",
        "shared_actions",
        "refunds",
        "outcomes",
        "api",
        "agui",
        "logging_setup",
        "telemetry",
    ):
        assert not (package_root() / f"{name}.py").exists(), name


def test_main_has_no_import_time_application() -> None:
    source = ast.parse((package_root() / "main.py").read_text())
    assert not any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "app" for target in node.targets)
        for node in source.body
    )
    text = (package_root() / "main.py").read_text()
    assert "maf_double_charge.api.app:create_app" in text
    assert "factory=True" in text


@pytest.mark.parametrize("router", ["cases", "runs", "streams", "assistant"])
def test_business_routes_use_application_services_not_repository_or_model(router: str) -> None:
    source = package_root() / "api" / "routers" / f"{router}.py"
    tree = ast.parse(source.read_text())
    forbidden_names = {
        "Repository", "RepositoryDependency", "ModelClient", "ModelDependency",
        "get_repository", "get_model", "get_runtime", "Runtime",
        "repository", "model", "runtime", "selected_run_facts", "selected_run_view",
        "workspace_view",
    }
    forbidden_attributes = {
        "repository", "model", "runtime", "explain_run", "get_state_by_case",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names, (router, node.lineno, node.id)
        elif isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_attributes, (router, node.lineno, node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            assert all(alias.name not in forbidden_names for alias in node.names)
            module = node.module or "" if isinstance(node, ast.ImportFrom) else ""
            assert not any(
                part in module.split(".")
                for part in ("persistence", "bootstrap", "clients", "testing")
            )


def test_projections_are_synchronous_transforms_without_io_dependencies() -> None:
    forbidden = {
        "api", "bootstrap", "infrastructure", "testing", "ports", "service",
        "psycopg", "psycopg_pool", "httpx", "aiohttp", "asyncio", "socket",
        "subprocess", "pathlib", "os", "builtins",
    }
    for source in (package_root() / "projections").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await)), source.name
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                assert not {alias.name for alias in node.names} & forbidden, source.name
            else:
                modules = []
            for module in modules:
                assert not set(module.split(".")) & forbidden, (source.name, module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "__import__", "eval", "exec"}, source.name


def test_hosted_business_reads_use_the_application_service() -> None:
    source = package_root().parents[2] / "infra/foundry-hosted/agent/main.py"
    tree = ast.parse(source.read_text())
    execute = next(
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_execute"
    )
    assert not any(
        isinstance(node, ast.Attribute) and node.attr in {"repository", "model"}
        for node in ast.walk(execute)
    )
    assert not any(
        isinstance(node, ast.Name) and node.id in {"repository", "model"}
        for node in ast.walk(execute)
    )
