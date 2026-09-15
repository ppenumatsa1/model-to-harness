"""Copy reviewed lane source into the direct-code Foundry Hosted Agent package."""

from __future__ import annotations

import shutil
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = LANE_ROOT.parents[2]
AGENT_ROOT = LANE_ROOT / "infra" / "foundry-hosted" / "agent"


def sync_package(source: Path, destination: Path) -> None:
    if not source.is_dir():
        relative_source = source.relative_to(REPOSITORY_ROOT)
        raise SystemExit(f"Required source directory is missing: {relative_source}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "testing"),
    )


def main() -> None:
    sync_package(
        LANE_ROOT / "backend" / "src" / "checkout_recovery_maf",
        AGENT_ROOT / "checkout_recovery_maf",
    )
    sync_package(
        REPOSITORY_ROOT / "shared" / "src" / "model_to_harness_shared",
        AGENT_ROOT / "model_to_harness_shared",
    )
    print(f"Prepared direct-code package: {AGENT_ROOT.relative_to(LANE_ROOT)}")


if __name__ == "__main__":
    main()
