import ast
from pathlib import Path


def test_shared_source_has_no_framework_runtime_or_cloud_imports() -> None:
    source_root = (
        Path(__file__).parents[1] / "src" / "model_to_harness_shared"
    )
    forbidden_roots = {
        "agent_framework",
        "azure",
        "fastapi",
        "langgraph",
        "opentelemetry",
        "psycopg",
        "sqlalchemy",
    }
    violations: list[str] = []

    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".", 1)[0] in forbidden_roots:
                    violations.append(f"{path.relative_to(source_root)} imports {name}")

    assert violations == []
