"""Copy reviewed lane source into the direct-code Foundry Hosted Agent package."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from hashlib import sha256
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from verify_release_dependencies import require_release_dependencies

LANE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = LANE_ROOT.parents[2]
AGENT_ROOT = LANE_ROOT / "infra" / "foundry-hosted" / "agent"
RUNTIME_VERSION = "1.0.85"
SDK_VERSION = "1.0.13"
PROTOCOL_VERSION = 3


def source_file(relative: Path) -> bool:
    """Only executable source and the reviewed native skill belong in a package."""
    if any(
        part.startswith(".") or part in {"__pycache__", "testing", "cache", "sessions"}
        for part in relative.parts
    ):
        return False
    return (
        relative.suffix == ".py"
        or relative.name == "py.typed"
        or relative.as_posix() == "sdk/skills/checkout-triage/SKILL.md"
    )


def runtime_files(root: Path) -> dict[str, Path]:
    manifest = root / "runtime-manifest.json"
    if not manifest.exists():
        return {}
    if manifest.is_symlink():
        raise ValueError("Runtime manifest must be a regular file")
    metadata = json.loads(manifest.read_text())
    if metadata.get("version") != RUNTIME_VERSION or metadata.get("platform") != "linux-x64":
        raise ValueError("Hosted runtime version or platform mismatch")
    if (
        metadata.get("sdk_version") != SDK_VERSION
        or metadata.get("protocol_version") != PROTOCOL_VERSION
    ):
        raise ValueError("Hosted SDK or runtime protocol mismatch")
    files = metadata.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Runtime manifest has no files")
    expected = {"runtime-manifest.json": manifest}
    for name, digest in files.items():
        path = Path(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.parts[:3] != ("copilot-runtime", "prebuilds", "linux-x64")
        ):
            raise ValueError("Runtime file is outside the approved bundle")
        source = root / path
        if (
            any(parent.is_symlink() for parent in [source, *source.parents] if parent != root)
            or not source.is_file()
            or sha256(source.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Runtime source does not match its pinned manifest")
        expected[name] = source
    return expected


def verify_code_archive(root: Path, content: bytes, expected_hash: str) -> dict[str, str | int]:
    """Verify downloaded ZIP bytes against a reviewed, prepared agent source directory."""
    digest = sha256(content).hexdigest()
    if digest != expected_hash.removeprefix("sha256:"):
        raise ValueError("Hosted archive digest mismatch")

    expected: dict[str, Path] = {}
    for name in ("main.py", "requirements.txt", "eval.yaml"):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Required Hosted source file is missing or not a regular file")
        expected[name] = path
    for package in ("checkout_recovery_copilot", "model_to_harness_shared"):
        directory = root / package
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Required Hosted package directory is missing or is a symlink")
        package_files = 0
        for path in directory.rglob("*"):
            relative = path.relative_to(root)
            if not source_file(path.relative_to(directory)):
                continue
            if path.is_symlink():
                raise ValueError("Hosted canonical source must not contain symlinks")
            if path.is_file():
                expected[relative.as_posix()] = path
                package_files += 1
        if not package_files:
            raise ValueError("Required Hosted package contains no canonical source files")
    expected.update(runtime_files(root))

    ignore = root / ".agentignore"
    if ignore.is_symlink():
        raise ValueError("Hosted ignore file must not be a symlink")
    optional = {".agentignore": ignore} if ignore.is_file() else {}
    allowed_directories = {
        parent.as_posix() + "/"
        for name in expected
        for parent in Path(name).parents
        if parent != Path(".")
    }
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("Hosted archive contains duplicate entries")
            files = {}
            for entry in entries:
                kind = stat.S_IFMT(entry.external_attr >> 16)
                if entry.is_dir():
                    if entry.filename not in allowed_directories or kind not in {0, stat.S_IFDIR}:
                        raise ValueError("Hosted archive contains an unexpected directory")
                else:
                    if kind not in {0, stat.S_IFREG}:
                        raise ValueError("Hosted archive contains a non-regular file")
                    files[entry.filename] = entry
            if (
                not set(expected) <= files.keys()
                or not files.keys() <= expected.keys() | optional.keys()
            ):
                raise ValueError("Hosted archive file set differs from canonical source")
            for name, entry in files.items():
                source = expected[name] if name in expected else optional[name]
                if archive.read(entry) != source.read_bytes():
                    raise ValueError("Hosted archive source content mismatch")
                # Hosted startup restores executable bits after verifying staged bytes.
    except BadZipFile as error:
        raise ValueError("Invalid Hosted code archive") from error
    require_release_dependencies(
        LANE_ROOT / "requirements-cloud.lock", requirements=expected["requirements.txt"].read_text()
    )
    return {"archive_sha256": digest, "files": len(files)}


def sync_package(source: Path, destination: Path) -> None:
    if not source.is_dir():
        relative_source = source.relative_to(REPOSITORY_ROOT)
        raise SystemExit(f"Required source directory is missing: {relative_source}")
    if destination.exists():
        shutil.rmtree(destination)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not source_file(relative):
            continue
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise SystemExit("Canonical source may not contain symlinks")
        if path.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def prepare_runtime() -> None:
    """Materialize the SDK's checksum-verified release during packaging, not cold start."""
    require_release_dependencies(LANE_ROOT / "requirements-cloud.lock", installed=True)
    if version("github-copilot-sdk") != SDK_VERSION:
        raise SystemExit("Installed SDK differs from the selected delivery version")
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise SystemExit("Hosted packaging requires Linux x86_64 (use the CI Linux runner)")
    runtime = AGENT_ROOT / "copilot-runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    subprocess.run(
        [sys.executable, "-m", "copilot", "download-runtime", "--version", RUNTIME_VERSION],
        check=True,
        env={
            **os.environ,
            "COPILOT_CLI_EXTRACT_DIR": str(runtime),
            "COPILOT_SKIP_CLI_DOWNLOAD": "false",
        },
    )
    subprocess.run(
        [
            sys.executable,
            str(LANE_ROOT / "scripts/verify_native_runtime.py"),
            "--binary",
            str(runtime / "prebuilds/linux-x64/copilot-runtime"),
            "--state-root",
            str(AGENT_ROOT),
        ],
        check=True,
        timeout=90,
    )
    files = {
        path.relative_to(AGENT_ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(runtime.rglob("*"))
        if path.is_file()
    }
    (AGENT_ROOT / "runtime-manifest.json").write_text(
        json.dumps(
            {
                "sdk_version": SDK_VERSION,
                "version": RUNTIME_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "platform": "linux-x64",
                "files": files,
            },
            indent=2,
        )
        + "\n"
    )
    runtime_files(AGENT_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-runtime", action="store_true")
    args = parser.parse_args()
    require_release_dependencies(LANE_ROOT / "requirements-cloud.lock", installed=True)
    from cloud_dependencies import verify

    verify(installed=True)
    requirements = (LANE_ROOT / "requirements-cloud.lock").read_text()
    require_release_dependencies(LANE_ROOT / "requirements-cloud.lock", requirements=requirements)
    AGENT_ROOT.mkdir(parents=True, exist_ok=True)
    (AGENT_ROOT / "requirements.txt").write_text(requirements)
    sync_package(
        LANE_ROOT / "backend" / "src" / "checkout_recovery_copilot",
        AGENT_ROOT / "checkout_recovery_copilot",
    )
    if args.with_runtime:
        prepare_runtime()
    else:
        shutil.rmtree(AGENT_ROOT / "copilot-runtime", ignore_errors=True)
        (AGENT_ROOT / "runtime-manifest.json").unlink(missing_ok=True)
    sync_package(
        REPOSITORY_ROOT / "shared" / "src" / "model_to_harness_shared",
        AGENT_ROOT / "model_to_harness_shared",
    )
    print(f"Prepared direct-code package: {AGENT_ROOT.relative_to(LANE_ROOT)}")


if __name__ == "__main__":
    main()
