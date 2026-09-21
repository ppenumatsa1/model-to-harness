import importlib.util
import json
import stat
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

LANE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "checkout_prepare_hosted", LANE / "scripts/prepare_hosted.py"
)
assert SPEC and SPEC.loader
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)
RUNTIME_SPEC = importlib.util.spec_from_file_location(
    "checkout_verify_runtime", LANE / "scripts/verify_native_runtime.py"
)
assert RUNTIME_SPEC and RUNTIME_SPEC.loader
runtime_verifier = importlib.util.module_from_spec(RUNTIME_SPEC)
RUNTIME_SPEC.loader.exec_module(runtime_verifier)


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "LANE_ROOT", tmp_path)
    requirements = f"urllib3==2.8.0 --hash=sha256:{'a' * 64}\n"
    (tmp_path / "requirements-cloud.lock").write_text(requirements)
    files = {
        "main.py": b"print('hosted')\n",
        "requirements.txt": requirements.encode(),
        "eval.yaml": b"name: checkout-start-contract\n",
        ".agentignore": (LANE / "infra/foundry-hosted/agent/.agentignore").read_bytes(),
        "checkout_recovery_copilot/__init__.py": b"",
        "checkout_recovery_copilot/sdk/skills/checkout-triage/SKILL.md": b"Read-only triage\n",
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
        "unreviewed.yaml",
        "../outside.py",
        "/absolute.py",
        "checkout_recovery_copilot/.env",
        "checkout_recovery_copilot/__pycache__/module.pyc",
        "checkout_recovery_copilot/testing/fakes.py",
        "checkout_recovery_copilot/cache/sentinel",
        "model_to_harness_shared/.venv/sentinel.py",
        "model_to_harness_shared/module.pyd",
        "checkout_recovery_copilot/sdk/native-session.json",
        "checkout_recovery_copilot/sdk/sessions/session.py",
        "checkout_recovery_copilot/sdk/skills/other/SKILL.md",
        "checkout_recovery_copilot/sdk/receipts.json",
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
@pytest.mark.parametrize("name", ["checkout_recovery_copilot/__init__.py", "eval.yaml"])
def test_missing_or_changed_canonical_source_is_rejected(source, change, name):
    root, files = source
    if change == "missing":
        del files[name]
    else:
        files[name] = b"changed"
    content = code_zip(files)
    with pytest.raises(ValueError, match="file set|content mismatch"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())


def test_wrong_digest_is_rejected(source):
    root, files = source
    with pytest.raises(ValueError, match="digest mismatch"):
        prepare.verify_code_archive(root, code_zip(files), "0" * 64)


@pytest.mark.parametrize("duplicate", ["main.py", "checkout_recovery_copilot/"])
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


@pytest.mark.parametrize("directory", [".venv/", ".foundry/", "checkout_recovery_copilot/testing/"])
def test_even_empty_unexpected_directories_are_rejected(source, directory):
    root, files = source
    content = code_zip({**files, directory: b""})
    with pytest.raises(ValueError, match="unexpected directory"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())


def test_canonical_directory_entries_are_allowed(source):
    root, files = source
    content = code_zip({**files, "checkout_recovery_copilot/": b""})
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


def test_sync_copies_only_reviewed_source_and_skill(source, tmp_path):
    root, _ = source
    package = root / "checkout_recovery_copilot"
    (package / "sdk/private-state.json").write_text("private")
    destination = tmp_path / "prepared"
    prepare.sync_package(package, destination)
    assert (destination / "sdk/skills/checkout-triage/SKILL.md").is_file()
    assert not (destination / "sdk/private-state.json").exists()
    assert (destination / "__init__.py").is_file()


def test_sync_rejects_symlinked_source(source, tmp_path):
    root, _ = source
    package = root / "checkout_recovery_copilot"
    (package / "escape.py").symlink_to(root / "main.py")
    with pytest.raises(SystemExit, match="symlinks"):
        prepare.sync_package(package, tmp_path / "prepared")


def test_pinned_runtime_archive_accepts_stripped_mode_but_rejects_changed_bytes_and_version(source):
    root, files = source
    name = "copilot-runtime/prebuilds/linux-x64/copilot-runtime"
    path = root / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"pinned-runtime")
    path.chmod(0o755)
    manifest = {
        "sdk_version": prepare.SDK_VERSION,
        "version": prepare.RUNTIME_VERSION,
        "protocol_version": prepare.PROTOCOL_VERSION,
        "platform": "linux-x64",
        "files": {name: sha256(path.read_bytes()).hexdigest()},
    }
    encoded = json.dumps(manifest).encode()
    (root / "runtime-manifest.json").write_bytes(encoded)
    files.update({name: path.read_bytes(), "runtime-manifest.json": encoded})
    content = code_zip(files)
    with ZipFile(BytesIO(content)) as uploaded:
        assert not (uploaded.getinfo(name).external_attr >> 16) & 0o111
    prepare.verify_code_archive(root, content, sha256(content).hexdigest())
    path.write_bytes(b"substituted")
    with pytest.raises(ValueError, match="pinned manifest"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())
    manifest["version"] = "unreviewed"
    (root / "runtime-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="version or platform"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())


def test_hosted_requirements_use_pinned_sdk_and_no_previous_framework():
    requirements = (LANE / "infra/foundry-hosted/agent/requirements.txt").read_text()
    assert "github-copilot-sdk==1.0.13" in requirements
    assert "azure-ai-agentserver-responses==2.1.0" in requirements
    assert "opentelemetry-proto==1.44.0" in requirements
    assert "agent-framework" not in requirements


def test_cloud_api_and_hosted_do_not_use_laptop_feed():
    dockerfile = (LANE / "backend/Dockerfile").read_text()
    requirements = (LANE / "infra/foundry-hosted/agent/requirements.txt").read_text()
    hosted = (LANE / "azure.yaml").read_text()
    assert "--default-index https://pypi.org/simple --require-hashes" in dockerfile
    assert "UV_DEFAULT_INDEX" not in hosted
    assert "--index-url" not in requirements
    assert "--trusted-host" not in requirements
    assert "packagefeedproxy.microsoft.io" not in requirements + hosted


@pytest.mark.parametrize("selected", ["1.0.12", "1.0.14", "2.0.0"])
def test_runtime_verifier_rejects_other_sdk_versions(monkeypatch, selected):
    monkeypatch.setattr(runtime_verifier, "version", lambda _: selected)
    with pytest.raises(ValueError, match="SDK differs"):
        runtime_verifier.require_sdk()


@pytest.mark.parametrize("runtime,protocol", [("1.0.83", 3), ("1.0.86", 3), ("1.0.85", 4)])
def test_runtime_verifier_rejects_actual_runtime_or_protocol(runtime, protocol):
    with pytest.raises(ValueError, match="Actual Copilot runtime"):
        runtime_verifier.validate_status(
            SimpleNamespace(version=runtime, protocol_version=protocol)
        )


def test_deliberate_runtime_pair_not_sdk_default(monkeypatch):
    from checkout_recovery_copilot.sdk import archive

    monkeypatch.setattr(runtime_verifier, "version", lambda _: "1.0.13")
    runtime_verifier.require_sdk()
    runtime_verifier.validate_status(SimpleNamespace(version="1.0.85", protocol_version=3))
    assert prepare.SDK_VERSION == runtime_verifier.SDK_VERSION == archive.SDK_VERSION
    assert prepare.RUNTIME_VERSION == runtime_verifier.RUNTIME_VERSION
    assert prepare.PROTOCOL_VERSION == runtime_verifier.PROTOCOL_VERSION
    dockerfile = (LANE / "backend/Dockerfile").read_text()
    assert "download-runtime --version 1.0.85" in dockerfile
    assert "/build/verify_native_runtime.py --binary /opt/copilot-runtime/" in dockerfile
    assert "chmod -R a+rX /opt/copilot-runtime" in dockerfile
    assert "--no-sources --no-build-isolation --wheel" in dockerfile
    assert "from checkout_recovery_copilot.main import create_app" in dockerfile
    assert "CHECKOUT_COPILOT_STATE_DIRECTORY=/home/checkout/copilot-state" in dockerfile


@pytest.mark.asyncio
async def test_runtime_probe_uses_explicit_binary_and_always_stops(monkeypatch, tmp_path):
    import copilot

    binary = tmp_path / "copilot-runtime"
    binary.write_text("test")
    binary.chmod(0o700)
    calls = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def start(self):
            calls.append("started")

        async def get_status(self):
            return SimpleNamespace(version="1.0.83", protocol_version=3)

        async def stop(self):
            calls.append("stopped")

    monkeypatch.setattr(runtime_verifier, "version", lambda _: "1.0.13")
    monkeypatch.setattr(copilot, "CopilotClient", Client)
    monkeypatch.setattr(
        copilot, "RuntimeConnection", SimpleNamespace(for_stdio=lambda **kwargs: kwargs)
    )
    with pytest.raises(ValueError, match="Actual Copilot runtime"):
        await runtime_verifier.verify_runtime(binary, tmp_path)
    assert calls[0]["connection"] == {"path": str(binary)}
    assert calls[0]["use_logged_in_user"] is False
    assert calls[0]["env"]["COPILOT_SKIP_CLI_DOWNLOAD"] == "true"
    assert calls[1:] == ["started", "stopped"]


def test_prepare_runtime_rejects_wrong_sdk_before_download(monkeypatch, source):
    monkeypatch.setattr("verify_release_dependencies.version", lambda _: "2.8.0")
    monkeypatch.setattr(prepare, "version", lambda _: "1.0.14")
    monkeypatch.setattr(
        prepare.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Runtime download must not start"),
    )
    with pytest.raises(SystemExit, match="Installed SDK differs"):
        prepare.prepare_runtime()


@pytest.mark.parametrize("version", ["2.7.0", "2.8.0rc1", "2.8.1"])
def test_matching_archive_digest_cannot_bless_unsafe_or_mismatched_dependencies(source, version):
    root, files = source
    files["requirements.txt"] = f"urllib3=={version}\n".encode()
    (root / "requirements.txt").write_bytes(files["requirements.txt"])
    content = code_zip(files)
    with pytest.raises(SystemExit, match="Release blocked"):
        prepare.verify_code_archive(root, content, sha256(content).hexdigest())


@pytest.mark.parametrize("key,value", [("sdk_version", "1.0.14"), ("protocol_version", 4)])
def test_runtime_manifest_rejects_unselected_pair(source, key, value):
    root, _ = source
    manifest = {
        "sdk_version": prepare.SDK_VERSION,
        "version": prepare.RUNTIME_VERSION,
        "protocol_version": prepare.PROTOCOL_VERSION,
        "platform": "linux-x64",
        key: value,
    }
    (root / "runtime-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="SDK or runtime protocol mismatch"):
        prepare.runtime_files(root)
