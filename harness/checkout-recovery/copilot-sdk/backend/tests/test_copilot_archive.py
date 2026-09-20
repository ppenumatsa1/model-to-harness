import base64
import copy
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from checkout_recovery_copilot.application.ports import InvestigationIncompleteError
from checkout_recovery_copilot.sdk import archive


@pytest.fixture
def directory():
    root = Path(".azure/copilot-archive-tests") / uuid4().hex
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root)


def native_state(directory):
    identifier = str(uuid4())
    root = directory / "source" / "session-state" / identifier
    root.mkdir(parents=True)
    (root / "events.jsonl").write_bytes(b'{"native":"opaque"}\n\x00')
    (root / "workspace.yaml").write_bytes(b"native: format\n")
    (directory / "source" / "credentials.json").write_text("NEVER-ARCHIVE")
    provenance = {
        "sdk_version": archive.SDK_VERSION,
        "runtime_version": archive.RUNTIME_VERSION,
        "protocol_version": 3,
    }
    return identifier, archive.snapshot(directory / "source", [identifier], provenance)


def test_opaque_roundtrip_excludes_global_credentials(directory):
    identifier, state = native_state(directory)
    assert "NEVER-ARCHIVE" not in repr(state)
    assert archive.restore(directory / "restored", state) == [identifier]
    for relative in state["sessions"][identifier]:
        assert (directory / "source" / "session-state" / identifier / relative).read_bytes() == (
            directory / "restored" / "session-state" / identifier / relative
        ).read_bytes()


def test_validate_is_pure_and_returns_detached_session_ids(directory, monkeypatch):
    identifier, state = native_state(directory)
    original = copy.deepcopy(state)

    def no_filesystem(*_args, **_kwargs):
        raise AssertionError("pure archive validation must not access the filesystem")

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", no_filesystem)
        scoped.setattr(Path, "mkdir", no_filesystem)
        identifiers = archive.validate(state)
    assert identifiers == [identifier]
    identifiers.clear()
    assert state == original


@pytest.mark.parametrize(
    "path",
    [
        "../credentials.json",
        "/etc/passwd",
        "files/../../oops",
        "files\\oops",
        "files//oops",
        "files/./oops",
        "files/.env",
        "files/auth-token.json",
        "config.json",
        "credentials.json",
        "files/\x00",
    ],
)
def test_archive_rejects_paths_before_writing(directory, path):
    identifier, state = native_state(directory)
    state["sessions"][identifier][path] = base64.b64encode(b"bad").decode()
    with pytest.raises(InvestigationIncompleteError):
        archive.validate(state)
    with pytest.raises(InvestigationIncompleteError):
        archive.restore(directory / "destination", state)
    assert not (directory / "destination").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("sdk_version", "2.0"),
        ("sdk_version", "1.0.14"),
        ("runtime_version", "future"),
        ("runtime_version", "1.0.83"),
        ("protocol_version", 100),
    ],
)
def test_archive_rejects_version_mismatch(directory, field, value):
    _, state = native_state(directory)
    state["provenance"][field] = value
    with pytest.raises(InvestigationIncompleteError):
        archive.restore(directory / "destination", state)


def test_archive_rejects_bad_encoding_limits_and_symlinks(directory, monkeypatch):
    identifier, state = native_state(directory)
    broken = copy.deepcopy(state)
    broken["sessions"][identifier]["events.jsonl"] = "$$"
    with pytest.raises(InvestigationIncompleteError):
        archive.restore(directory / "bad-encoding", broken)
    monkeypatch.setattr(archive, "MAX_FILE_BYTES", 1)
    with pytest.raises(InvestigationIncompleteError):
        archive.restore(directory / "large-file", state)
    monkeypatch.setattr(archive, "MAX_FILE_BYTES", 4096)
    monkeypatch.setattr(archive, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(InvestigationIncompleteError):
        archive.restore(directory / "large-archive", state)
    monkeypatch.setattr(archive, "MAX_ARCHIVE_BYTES", 4096)
    monkeypatch.setattr(archive, "MAX_FILES", 1)
    with pytest.raises(InvestigationIncompleteError):
        archive.restore(directory / "many-files", state)
    monkeypatch.setattr(archive, "MAX_FILES", 256)
    root = directory / "source" / "session-state" / identifier
    (root / "plan.md").symlink_to(root / "events.jsonl")
    with pytest.raises(InvestigationIncompleteError):
        archive.snapshot(directory / "source", [identifier], state["provenance"])
    destination = directory / "symlink-base"
    destination.symlink_to(directory / "source", target_is_directory=True)
    with pytest.raises(InvestigationIncompleteError):
        archive.restore(destination, state)


def test_archive_rejects_invalid_session_and_nonfresh_root(directory):
    _, state = native_state(directory)
    with pytest.raises(InvestigationIncompleteError):
        archive.restore(directory / "source", state)
    state["sessions"]["../escape"] = state["sessions"].pop(next(iter(state["sessions"])))
    with pytest.raises(InvestigationIncompleteError):
        archive.restore(directory / "other", state)
