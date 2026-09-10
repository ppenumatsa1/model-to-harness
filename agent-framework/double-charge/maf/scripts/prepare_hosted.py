from __future__ import annotations

import shutil
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = LANE_ROOT.parents[2]
AGENT_ROOT = LANE_ROOT / "infra" / "foundry-hosted" / "agent"


def sync_package(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def main() -> None:
    sync_package(
        LANE_ROOT / "backend" / "src" / "maf_double_charge",
        AGENT_ROOT / "maf_double_charge",
    )
    sync_package(
        REPOSITORY_ROOT / "shared" / "src" / "model_to_harness_shared",
        AGENT_ROOT / "model_to_harness_shared",
    )
    sync_package(
        LANE_ROOT / "backend" / "migrations",
        AGENT_ROOT / "maf_double_charge" / "_migrations",
    )
    print(f"Prepared hosted source in {AGENT_ROOT}")


if __name__ == "__main__":
    main()
