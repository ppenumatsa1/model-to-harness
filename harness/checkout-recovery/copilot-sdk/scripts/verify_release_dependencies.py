"""Offline, lane-owned urllib3 release hold; not a general vulnerability scanner."""

from __future__ import annotations

import argparse
import re
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

RELEASE_HOLD = (
    "Release blocked: require stable urllib3>=2.8.0 in the cloud lock and matching packaged "
    "requirements/installed dependencies. Missing, prerelease or mismatched candidates "
    "are not releasable. Obtain the patched package through an authorized source, "
    "regenerate the lock and Hosted requirements, rebuild and revalidate; do not "
    "downgrade cloud dependencies or waive the security hold."
)


def cloud_pins(requirements: str) -> dict[str, str]:
    """Cloud artifacts permit only exact, hashed, index-independent requirement entries."""
    pins = {}
    for line in requirements.replace("\\\n", " ").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        pin = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.!+_-]*)"
            r"(?:\s+--hash=sha256:[0-9a-f]{64})+\s*",
            line.strip(),
        )
        if not pin:
            raise ValueError("Cloud requirements must use exact SHA-256 hashed pins")
        name = re.sub(r"[-_.]+", "-", pin[1]).lower()
        if name in pins:
            raise ValueError("Duplicate cloud dependency")
        pins[name] = pin[2]
    if not pins:
        raise ValueError("Empty cloud lock")
    return pins


def stable_patched(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.post\d+)?", value, flags=re.ASCII)
    return bool(match and tuple(map(int, match.groups())) >= (2, 8, 0))


def require_release_dependencies(
    lock: Path, *, requirements: str | None = None, installed: bool = False
) -> None:
    """Check artifact inputs first; a patched developer venv cannot bless an old lock."""
    try:
        if lock.name != "uv.lock":
            locked = lock.read_text()
            pins = cloud_pins(locked)
            if not stable_patched(pins.get("urllib3")):
                raise ValueError
            if requirements is not None and requirements != locked:
                raise ValueError
            if installed and any(version(name) != selected for name, selected in pins.items()):
                raise ValueError
            return
        with lock.open("rb") as stream:
            packages = tomllib.load(stream)["package"]
        candidates = [item["version"] for item in packages if item.get("name") == "urllib3"]
        if len(candidates) != 1 or not stable_patched(candidates[0]):
            raise ValueError
        selected = candidates[0]
        if requirements is not None:
            lines = requirements.replace("\\\n", " ").splitlines()
            pins = [
                line.strip()
                for line in lines
                if re.match(r"^\s*urllib3(?:\b|\[)", line, flags=re.IGNORECASE)
            ]
            if len(pins) != 1:
                raise ValueError
            pin = re.fullmatch(
                r"urllib3==([^\s;]+)(?:\s+--hash=sha256:[0-9a-f]{64})*\s*",
                pins[0],
                flags=re.IGNORECASE,
            )
            if not pin or pin[1] != selected:
                raise ValueError
        if installed and version("urllib3") != selected:
            raise ValueError
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        UnicodeError,
        PackageNotFoundError,
    ):
        raise SystemExit(RELEASE_HOLD) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--requirements", type=Path)
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    try:
        requirements = args.requirements.read_text() if args.requirements else None
    except (OSError, UnicodeError):
        raise SystemExit(RELEASE_HOLD) from None
    require_release_dependencies(args.lock, requirements=requirements, installed=args.installed)
    print("Verified urllib3 release dependency gate")


if __name__ == "__main__":
    main()
