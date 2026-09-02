from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = LANE_ROOT.parents[2]
AGENT_ROOT = LANE_ROOT / "infra" / "foundry-hosted" / "agent"
PACKAGES_ROOT = AGENT_ROOT / "_packages"


def sync_package(source: Path, target: Path) -> dict[str, str]:
    target.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for source_file in sorted(source.rglob("*")):
        if not source_file.is_file():
            continue
        if "__pycache__" in source_file.parts or source_file.suffix in {".pyc", ".pyo"}:
            continue
        relative = source_file.relative_to(source)
        target_file = target / relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target_file)
        manifest[target_file.relative_to(AGENT_ROOT).as_posix()] = hashlib.sha256(
            source_file.read_bytes()
        ).hexdigest()
    return manifest


def main() -> None:
    if PACKAGES_ROOT.exists():
        shutil.rmtree(PACKAGES_ROOT)

    manifest = {}
    manifest.update(
        sync_package(
            LANE_ROOT / "backend" / "src" / "model_to_harness_langgraph",
            PACKAGES_ROOT / "model_to_harness_langgraph",
        )
    )
    manifest.update(
        sync_package(
            REPOSITORY_ROOT / "shared" / "src" / "model_to_harness_shared",
            PACKAGES_ROOT / "model_to_harness_shared",
        )
    )
    (AGENT_ROOT / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared {len(manifest)} hosted source files in {AGENT_ROOT}")


if __name__ == "__main__":
    main()
