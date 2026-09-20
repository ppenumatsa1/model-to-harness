"""Lock, install and verify the independent public-PyPI cloud dependency profile."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tomllib
from hashlib import sha256
from pathlib import Path

from verify_release_dependencies import cloud_pins, require_release_dependencies

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT.parents[2] / "shared"
INDEX = "https://pypi.org/simple"
RUNTIME_LOCK = "requirements-cloud.lock"
DEV_LOCK = "requirements-cloud-dev.lock"
MANIFEST = "dependency-profiles.json"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def inputs() -> dict[str, str]:
    return {
        "pyproject.toml": digest(ROOT / "pyproject.toml"),
        "../../../shared/pyproject.toml": digest(SHARED / "pyproject.toml"),
        "scripts/cloud_dependencies.py": digest(Path(__file__)),
    }


def environment() -> dict[str, str]:
    # Ignore inherited resolver/index overrides without altering local project configuration.
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("UV_", "PIP_")) and key != "VIRTUAL_ENV"
    }
    scratch = ROOT / ".artifacts/cloud-dependencies"
    scratch.mkdir(parents=True, exist_ok=True)
    env.update({"TMPDIR": str(scratch), "UV_NO_PROGRESS": "1"})
    return env


def uv(*args: str) -> None:
    subprocess.run(["uv", "--no-config", *args], cwd=ROOT, env=environment(), check=True)


def verify(*, installed: bool = False) -> None:
    require_release_dependencies(ROOT / RUNTIME_LOCK, installed=installed)
    try:
        recorded = json.loads((ROOT / MANIFEST).read_text())
        if recorded["inputs"] != inputs() or recorded["index"] != INDEX:
            raise ValueError
        if (
            recorded["sdk_version"], recorded["runtime_version"], recorded["protocol_version"]
        ) != ("1.0.13", "1.0.85", 3):
            raise ValueError
        for name in (RUNTIME_LOCK, DEV_LOCK):
            if recorded["locks"][name] != digest(ROOT / name):
                raise ValueError
        runtime = cloud_pins((ROOT / RUNTIME_LOCK).read_text())
        dev = cloud_pins((ROOT / DEV_LOCK).read_text())
        if any(dev.get(name) != selected for name, selected in runtime.items()):
            raise ValueError
        if runtime.get("github-copilot-sdk") != "1.0.13":
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit("Cloud profile drift: regenerate and revalidate the cloud locks") from None


def lock() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    shared = tomllib.loads((SHARED / "pyproject.toml").read_text())
    dependencies = [
        item for item in project["project"]["dependencies"]
        if not item.startswith("model-to-harness-shared")
    ]
    dependencies += shared["project"]["dependencies"] + ["urllib3>=2.8.0"]
    scratch = ROOT / ".artifacts/cloud-dependencies"
    environment()
    runtime_input = scratch / "runtime.in"
    runtime_input.write_text("\n".join(dependencies) + "\n")
    development = (
        dependencies + project["project"]["optional-dependencies"]["dev"]
        + project["build-system"]["requires"] + shared["build-system"]["requires"]
    )
    dev_input = scratch / "development.in"
    dev_input.write_text("\n".join(development) + "\n")
    common = (
        "--default-index", INDEX, "--no-sources", "--generate-hashes",
        "--no-header", "--no-annotate", "--prerelease", "if-necessary-or-explicit",
        "--python-version", "3.13", "--python-platform", "x86_64-unknown-linux-gnu",
    )
    uv("pip", "compile", str(runtime_input), *common, "--output-file", RUNTIME_LOCK, "--quiet")
    uv(
        "pip", "compile", str(dev_input), *common, "--constraint", RUNTIME_LOCK,
        "--output-file", DEV_LOCK, "--quiet",
    )
    require_release_dependencies(ROOT / RUNTIME_LOCK)
    runtime = cloud_pins((ROOT / RUNTIME_LOCK).read_text())
    local = {
        row["name"]: row["version"]
        for row in tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    }
    manifest = {
        "schema": 1,
        "index": INDEX,
        "python": "3.13",
        "platform": "linux-x86_64",
        "sdk_version": "1.0.13",
        "runtime_version": "1.0.85",
        "protocol_version": 3,
        "inputs": inputs(),
        "locks": {name: digest(ROOT / name) for name in (RUNTIME_LOCK, DEV_LOCK)},
        "local_lock_sha256": digest(ROOT / "uv.lock"),
        "differences": {
            name: {"local": local.get(name), "cloud": selected}
            for name, selected in runtime.items() if local.get(name) != selected
        },
    }
    (ROOT / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    verify()


def sync() -> None:
    verify()
    python = ROOT / ".venv-cloud/bin/python"
    if not python.exists():
        uv("venv", "--python", "3.13", str(ROOT / ".venv-cloud"))
    uv(
        "pip", "sync", "--python", str(python), "--default-index", INDEX,
        "--require-hashes", DEV_LOCK,
    )
    uv(
        "pip", "install", "--python", str(python), "--no-deps", "--no-sources",
        "--no-build-isolation", str(SHARED), str(ROOT),
    )
    subprocess.run(
        [str(python), str(Path(__file__)), "verify", "--installed"],
        cwd=ROOT, env=environment(), check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("lock", "sync", "verify"))
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    if args.command == "lock":
        lock()
    elif args.command == "sync":
        sync()
    else:
        verify(installed=args.installed)
    print(f"Cloud dependency profile {args.command}: verified")


if __name__ == "__main__":
    main()
