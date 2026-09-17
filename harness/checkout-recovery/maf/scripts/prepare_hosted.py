"""Copy reviewed lane source into the direct-code Foundry Hosted Agent package."""

from __future__ import annotations

import shutil
import stat
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

LANE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = LANE_ROOT.parents[2]
AGENT_ROOT = LANE_ROOT / "infra" / "foundry-hosted" / "agent"


def verify_code_archive(root: Path, content: bytes, expected_hash: str) -> dict[str, str | int]:
    """Verify downloaded ZIP bytes against a reviewed, prepared agent source directory."""
    digest = sha256(content).hexdigest()
    if digest != expected_hash.removeprefix("sha256:"):
        raise ValueError("Hosted archive digest mismatch")

    expected: dict[str, Path] = {}
    for name in ("main.py", "requirements.txt", "README.md", "eval.yaml"):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Required Hosted source file is missing or not a regular file")
        expected[name] = path
    for package in ("checkout_recovery_maf", "model_to_harness_shared"):
        directory = root / package
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Required Hosted package directory is missing or is a symlink")
        package_files = 0
        for path in directory.rglob("*"):
            relative = path.relative_to(root)
            if any(
                part.startswith(".") or part in {"__pycache__", "testing", "cache"}
                for part in relative.parts
            ) or path.suffix in {".pyc", ".pyo", ".pyd"}:
                continue
            if path.is_symlink():
                raise ValueError("Hosted canonical source must not contain symlinks")
            if path.is_file():
                expected[relative.as_posix()] = path
                package_files += 1
        if not package_files:
            raise ValueError("Required Hosted package contains no canonical source files")

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
    except BadZipFile as error:
        raise ValueError("Invalid Hosted code archive") from error
    return {"archive_sha256": digest, "files": len(files)}


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
