import json
from pathlib import Path

import cloud_dependencies as profile
import pytest
import verify_release_dependencies as gate

LANE = Path(__file__).resolve().parents[2]


def hashed(name, version):
    return f"{name}=={version} --hash=sha256:{'a' * 64}\n"


@pytest.mark.parametrize(
    "content",
    [
        "",
        "urllib3>=2.8.0\n",
        "urllib3==2.8.0\n",
        hashed("urllib3", "2.8.*"),
        "--index-url https://example.invalid\n" + hashed("urllib3", "2.8.0"),
        hashed("urllib3", "2.8.0") * 2,
        hashed("urllib3", "2.8.0") + "other @ https://example.invalid/package.whl\n",
    ],
)
def test_cloud_lock_rejects_unhashed_or_unreviewed_inputs(tmp_path, content):
    lock = tmp_path / "requirements-cloud.lock"
    lock.write_text(content)
    with pytest.raises(SystemExit, match="Release blocked"):
        gate.require_release_dependencies(lock)


def test_cloud_requires_all_installed_pins_not_only_patched_urllib3(tmp_path, monkeypatch):
    lock = tmp_path / "requirements-cloud.lock"
    lock.write_text(hashed("urllib3", "2.8.0") + hashed("github-copilot-sdk", "1.0.13"))
    monkeypatch.setattr(
        gate, "version", lambda name: "2.8.0" if name == "urllib3" else "1.0.14"
    )
    with pytest.raises(SystemExit, match="Release blocked"):
        gate.require_release_dependencies(lock, installed=True)


def test_laptop_lock_does_not_authorize_cloud_release():
    with pytest.raises(SystemExit, match="Release blocked"):
        gate.require_release_dependencies(LANE / "uv.lock")
    gate.require_release_dependencies(LANE / "requirements-cloud.lock", installed=True)


def test_canonical_cloud_profile_records_local_difference_and_exact_native_pair():
    profile.verify(installed=True)
    metadata = json.loads((LANE / "dependency-profiles.json").read_text())
    assert metadata["differences"]["urllib3"]["local"] == "2.7.0"
    assert gate.stable_patched(metadata["differences"]["urllib3"]["cloud"])
    assert metadata["sdk_version"] == "1.0.13"
    assert metadata["runtime_version"] == "1.0.85"
    assert metadata["protocol_version"] == 3
    assert metadata["local_lock_sha256"] == profile.digest(LANE / "uv.lock")
    assert (LANE / "infra/foundry-hosted/agent/requirements.txt").read_bytes() == (
        LANE / "requirements-cloud.lock"
    ).read_bytes()


def test_cloud_environment_ignores_inherited_laptop_resolver_overrides(monkeypatch):
    monkeypatch.setenv("UV_DEFAULT_INDEX", "https://example.invalid")
    monkeypatch.setenv("PIP_INDEX_URL", "https://example.invalid")
    monkeypatch.setenv("VIRTUAL_ENV", "/example/laptop")
    actual = profile.environment()
    assert not {"UV_DEFAULT_INDEX", "PIP_INDEX_URL", "VIRTUAL_ENV"} & actual.keys()


def test_deployment_and_ci_never_implicitly_select_local_environment():
    hook = (LANE / "azure.yaml").read_text().split("hooks:", 1)[1]
    ci = (LANE.parents[2] / ".github/workflows/checkout-copilot.yml").read_text()
    release = (LANE / "scripts/release.py").read_text()
    assert ".venv-cloud/bin/python scripts/prepare_hosted.py" in hook
    assert "uv run" not in hook + ci
    assert '"run",\n                "python"' not in release
    assert "requirements-cloud.lock" in release
    assert ".venv-cloud/bin/python -m pytest" in ci
