import importlib.util
import stat
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

LANE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "checkout_prepare_hosted", LANE / "scripts/prepare_hosted.py"
)
assert SPEC and SPEC.loader
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


@pytest.fixture
def source(tmp_path):
    files = {
        "main.py": b"print('hosted')\n",
        "requirements.txt": b"example==1.0\n",
        "README.md": b"Hosted source\n",
        ".agentignore": (LANE / "infra/foundry-hosted/agent/.agentignore").read_bytes(),
        "checkout_recovery_maf/__init__.py": b"",
        "checkout_recovery_maf/maf/skills/checkout-triage/SKILL.md": b"Read-only triage\n",
        "model_to_harness_shared/__init__.py": b"",
        "model_to_harness_shared/py.typed": b"",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return tmp_path, files


def code_zip(files):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize("include_ignore", [True, False])
@pytest.mark.parametrize("hash_prefix", ["", "sha256:"])
def test_clean_archive_exactly_matches_canonical_source(source, include_ignore, hash_prefix):
    root, files = source
    if not include_ignore:
        del files[".agentignore"]
    content = code_zip(files)
    digest = sha256(content).hexdigest()
    assert prepare.verify_code_archive(root, content, hash_prefix + digest) == {
        "archive_sha256": digest,
        "files": len(files),
    }


@pytest.mark.parametrize(
    "extra",
    [
        ".venv/lib/site-packages/sentinel.py",
        ".env",
        ".env.production",
        ".foundry/private.json",
        ".azure/config.json",
        ".pytest_cache/sentinel",
        ".ruff_cache/sentinel",
        "unreviewed.py",
        "../outside.py",
        "/absolute.py",
        "checkout_recovery_maf/.env",
        "checkout_recovery_maf/__pycache__/module.pyc",
        "checkout_recovery_maf/testing/fakes.py",
        "checkout_recovery_maf/cache/sentinel",
        "model_to_harness_shared/.venv/sentinel.py",
        "model_to_harness_shared/module.pyd",
    ],
)
def test_private_or_unexpected_archive_files_are_rejected(source, extra):
    root, files = source
    if not extra.startswith(("/", "..")):
        path = root / extra
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PRIVATE-SENTINEL")
    clean = code_zip(files)
    prepare.verify_code_archive(root, clean, sha256(clean).hexdigest())
    contaminated = code_zip({**files, extra: b"PRIVATE-SENTINEL"})
    with pytest.raises(ValueError, match="file set"):
        prepare.verify_code_archive(root, contaminated, sha256(contaminated).hexdigest())


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_missing_or_changed_canonical_source_is_rejected(source, change):
    root, files = source
    if change == "missing":
        del files["checkout_recovery_maf/__init__.py"]
    else:
        files["checkout_recovery_maf/__init__.py"] = b"changed"
    content = code_zip(files)
    with pytest.raises(ValueError, match="file set|content mismatch"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())


def test_wrong_digest_is_rejected(source):
    root, files = source
    with pytest.raises(ValueError, match="digest mismatch"):
        prepare.verify_code_archive(root, code_zip(files), "0" * 64)


@pytest.mark.parametrize("duplicate", ["main.py", "checkout_recovery_maf/"])
def test_duplicate_files_and_directories_are_rejected(source, duplicate):
    root, files = source
    output = BytesIO(code_zip(files))
    with ZipFile(output, "a") as archive:
        if duplicate.endswith("/"):
            archive.writestr(duplicate, b"")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(duplicate, b"")
    content = output.getvalue()
    with pytest.raises(ValueError, match="duplicate"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())


@pytest.mark.parametrize("directory", [".venv/", ".foundry/", "checkout_recovery_maf/testing/"])
def test_even_empty_unexpected_directories_are_rejected(source, directory):
    root, files = source
    content = code_zip({**files, directory: b""})
    with pytest.raises(ValueError, match="unexpected directory"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())


def test_canonical_directory_entries_are_allowed(source):
    root, files = source
    content = code_zip({**files, "checkout_recovery_maf/": b""})
    prepare.verify_code_archive(root, content, sha256(content).hexdigest())


def test_archive_symlink_is_not_canonical_source(source):
    root, files = source
    del files["main.py"]
    output = BytesIO(code_zip(files))
    with ZipFile(output, "a") as archive:
        entry = ZipInfo("main.py")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(entry, b"print('hosted')\n")
    content = output.getvalue()
    with pytest.raises(ValueError, match="non-regular"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())


def test_corrupt_zip_is_rejected(source):
    root, _ = source
    content = b"not a zip"
    with pytest.raises(ValueError, match="Invalid Hosted"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())


def test_agentignore_excludes_local_install_and_private_artifacts():
    patterns = set((LANE / "infra/foundry-hosted/agent/.agentignore").read_text().splitlines())
    assert {
        "__pycache__/",
        "*.py[cod]",
        ".foundry/",
        ".venv/",
        ".env",
        ".env.*",
        ".azure/",
        ".pytest_cache/",
        ".ruff_cache/",
    } <= patterns
