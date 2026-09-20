"""Hash canonical release inputs without requiring a commit or a clean sibling lane."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[2]


def snapshot() -> dict:
    roots = [
        ROOT / "backend/src",
        ROOT / "backend/migrations",
        ROOT / "backend/Dockerfile",
        ROOT / "frontend/src",
        ROOT / "frontend/e2e",
        ROOT / "frontend/nginx",
        ROOT / "frontend/Dockerfile",
        ROOT / "frontend/Dockerfile.dockerignore",
        ROOT / "frontend/.npmrc",
        ROOT / "frontend/index.html",
        ROOT / "scripts",
        ROOT / "evals",
        ROOT / "infra/app",
        REPOSITORY / "shared/src",
        REPOSITORY / "shared/pyproject.toml",
        REPOSITORY / "shared/README.md",
        REPOSITORY / "LICENSE",
    ]
    roots += [
        ROOT / name
        for name in (
            "pyproject.toml", "uv.lock", "requirements-cloud.lock", "requirements-cloud-dev.lock",
            "dependency-profiles.json", "azure.yaml", "README.md", ".dockerignore",
        )
    ]
    roots += sorted((ROOT / "frontend").glob("*.json"))
    roots += sorted((ROOT / "frontend").glob("*.ts"))
    roots += [
        ROOT / "infra/foundry-hosted/agent" / name
        for name in ("main.py", "eval.yaml", ".agentignore", "requirements.txt")
    ]
    files = {}
    for root in roots:
        if not root.exists():
            raise ValueError(f"Missing canonical release input: {root.relative_to(REPOSITORY)}")
        for path in sorted(root.rglob("*")) if root.is_dir() else [root]:
            relative = path.relative_to(REPOSITORY)
            if any(
                part in {"__pycache__", "node_modules", "cache", ".venv", ".azure", ".foundry"}
                or part.startswith(".env")
                for part in relative.parts
            ) or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.is_symlink():
                raise ValueError("Release inputs must not contain symlinks")
            if path.is_file():
                files[relative.as_posix()] = sha256(path.read_bytes()).hexdigest()
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"schema": 1, "source_sha256": sha256(encoded).hexdigest(), "files": files}


def verify(path: Path) -> str:
    expected = json.loads(path.read_text())
    actual = snapshot()
    if expected != actual:
        raise SystemExit("Canonical source changed since the saved source manifest")
    return actual["source_sha256"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        print(verify(args.output))
    else:
        value = snapshot()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        print(value["source_sha256"])


if __name__ == "__main__":
    main()
