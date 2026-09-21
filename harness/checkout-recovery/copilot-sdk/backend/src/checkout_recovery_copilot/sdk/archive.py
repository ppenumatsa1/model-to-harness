"""Protected byte-for-byte archive of quiescent, SDK-owned session files.

This is not a transcript format. Only the pinned runtime interprets the files.
The application stores this object privately with the case transaction.
"""

import base64
import binascii
import re
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from checkout_recovery_copilot.application.ports import InvestigationIncompleteError

FORMAT = "copilot-native-session-v1"
SDK_VERSION = "1.0.13"
RUNTIME_VERSION = "1.0.85"
MAX_FILES = 256
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 12 * 1024 * 1024
_ROOT_FILES = {"events.jsonl", "workspace.yaml", "plan.md", ".workspace-fork.lock"}
_DIRECTORIES = {"checkpoints", "files"}
_FORBIDDEN = re.compile(r"(^\.env($|\.)|credential|token|secret|^config(\.|$))", re.I)


def _invalid() -> InvestigationIncompleteError:
    return InvestigationIncompleteError("native session archive validation failed")


def session_id(value: Any) -> str:
    if not isinstance(value, str):
        raise _invalid()
    try:
        if str(UUID(value)) != value:
            raise _invalid()
    except ValueError:
        raise _invalid() from None
    return value


def relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise _invalid()
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {".", ".."} or _FORBIDDEN.search(part) for part in path.parts)
    ):
        raise _invalid()
    if (len(path.parts) == 1 and value not in _ROOT_FILES) or (
        len(path.parts) > 1 and path.parts[0] not in _DIRECTORIES
    ):
        raise _invalid()
    return path


def snapshot(base: Path, ids: list[str], provenance: dict[str, Any]) -> dict[str, Any]:
    files: dict[str, dict[str, str]] = {}
    count = total = 0
    for identifier in ids:
        root = base / "session-state" / session_id(identifier)
        if not root.is_dir() or root.is_symlink() or root.parent.is_symlink():
            raise _invalid()
        entries: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise _invalid()
            if path.is_dir():
                continue
            name = str(path.relative_to(root))
            relative_path(name)
            if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                raise _invalid()
            data = path.read_bytes()
            total += len(data)
            count += 1
            if total > MAX_ARCHIVE_BYTES or count > MAX_FILES:
                raise _invalid()
            entries[name] = base64.b64encode(data).decode("ascii")
        if not entries:
            raise _invalid()
        files[identifier] = entries
    return {"format": FORMAT, "provenance": provenance, "sessions": files}


def _validated_files(
    state: dict[str, Any],
) -> tuple[list[str], list[tuple[str, PurePosixPath, bytes]]]:
    if not isinstance(state, dict):
        raise _invalid()
    provenance = state.get("provenance", {})
    if (
        state.get("format") != FORMAT
        or not isinstance(provenance, dict)
        or provenance.get("sdk_version") != SDK_VERSION
        or provenance.get("runtime_version") != RUNTIME_VERSION
        or provenance.get("protocol_version") != 3
    ):
        raise _invalid()
    sessions = state.get("sessions")
    if not isinstance(sessions, dict) or not 1 <= len(sessions) <= 2:
        raise _invalid()
    decoded: list[tuple[str, PurePosixPath, bytes]] = []
    total = 0
    for identifier, files in sessions.items():
        session_id(identifier)
        if not isinstance(files, dict) or not files:
            raise _invalid()
        for name, encoded in files.items():
            path = relative_path(name)
            if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_FILE_BYTES + 2) // 3):
                raise _invalid()
            try:
                data = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise _invalid() from None
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_ARCHIVE_BYTES:
                raise _invalid()
            decoded.append((identifier, path, data))
            if len(decoded) > MAX_FILES:
                raise _invalid()
    return list(sessions), decoded


def validate(state: dict[str, Any]) -> list[str]:
    """Validate the complete native archive without reading or writing files."""
    identifiers, _ = _validated_files(state)
    return identifiers


def restore(base: Path, state: dict[str, Any]) -> list[str]:
    identifiers, decoded = _validated_files(state)
    # Validate everything before creating files. Restore only into a fresh root.
    root = base / "session-state"
    if base.is_symlink() or root.exists() or root.is_symlink():
        raise _invalid()
    root.mkdir(parents=True, mode=0o700)
    for identifier, relative, data in decoded:
        destination = root / identifier / relative
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with destination.open("xb") as stream:
            stream.write(data)
        destination.chmod(0o600)
    return identifiers
