from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import maf_double_charge


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
