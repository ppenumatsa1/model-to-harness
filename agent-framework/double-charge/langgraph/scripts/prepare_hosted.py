"""Prepare only reviewed runtime files; generated evaluation artifacts are never packaged."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = LANE_ROOT.parents[2]
AGENT_ROOT = LANE_ROOT / "infra/foundry-hosted/agent"


def runtime_files(source: Path) -> list[Path]:
    files = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Runtime sources must not contain symbolic links")
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in {".py", ".sql"} and path.name != "py.typed":
            continue
        if any(part.startswith(".") for part in path.relative_to(source).parts):
            raise ValueError("Hidden runtime source is not allowed")
        files.append(path)
    return files


def prepare(target: Path = AGENT_ROOT) -> dict[str, str]:
    if target.is_symlink():
        raise ValueError("Hosted staging must not be a symbolic link")
    target = target.resolve()
    if target != AGENT_ROOT.resolve() and (
        target == REPOSITORY_ROOT or REPOSITORY_ROOT in target.parents
    ):
        raise ValueError("Alternate hosted staging must be outside the checkout")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    packages = target / "_packages"
    if packages.is_symlink():
        raise ValueError("Hosted package target must not be a symbolic link")
    if packages.exists():
        if target != AGENT_ROOT.resolve() and not (target / "SOURCE_MANIFEST.json").is_file():
            raise ValueError("Refusing to replace an unrecognized package directory")
        shutil.rmtree(packages)
    for name, source in (
        ("model_to_harness_langgraph", LANE_ROOT / "backend/src/model_to_harness_langgraph"),
        ("model_to_harness_shared", REPOSITORY_ROOT / "shared/src/model_to_harness_shared"),
    ):
        for path in runtime_files(source):
            destination = packages / name / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    # This mirrors the wheel's force-include contract; SQL has a single authoritative source.
    migrations = packages / "model_to_harness_langgraph/infrastructure/persistence/sql"
    migrations.mkdir(parents=True, exist_ok=True)
    sql_files = sorted((LANE_ROOT / "backend/migrations").glob("*.sql"))
    if not sql_files:
        raise ValueError("No authoritative application migrations found")
    for path in sql_files:
        shutil.copyfile(path, migrations / path.name)
    if target != AGENT_ROOT:
        for name in ("main.py", "requirements.txt", ".agentignore"):
            if (AGENT_ROOT / name).is_symlink():
                raise ValueError("Hosted entry files must not be symbolic links")
            shutil.copyfile(AGENT_ROOT / name, target / name)
    files = [target / "main.py", target / "requirements.txt", *runtime_files(packages)]
    manifest = {
        path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    (target / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=AGENT_ROOT)
    args = parser.parse_args()
    try:
        manifest = prepare(args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Hosted preparation failed: {type(exc).__name__}\n")
    print(f"Prepared {len(manifest)} allowlisted hosted files")


if __name__ == "__main__":
    main()
