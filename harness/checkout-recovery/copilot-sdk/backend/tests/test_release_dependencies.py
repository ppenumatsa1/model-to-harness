import importlib
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest
import verify_release_dependencies as gate

LANE = Path(__file__).resolve().parents[2]


def write_lock(root, version):
    lock = root / "uv.lock"
    lock.write_text(f'[[package]]\nname = "urllib3"\nversion = "{version}"\n')
    return lock


def write_cloud_lock(root, version):
    lock = root / "requirements-cloud.lock"
    lock.write_text(f"urllib3=={version} --hash=sha256:{'a' * 64}\n")
    return lock


@pytest.mark.parametrize(
    "version",
    ["2.7.0", "2.8.0rc1", "2.8.0a1", "2.9.0b1", "3.0.0.dev1", "invalid", "2.8.*"],
)
def test_vulnerable_and_nonfinal_lock_rejected_even_with_patched_environment(
    tmp_path, monkeypatch, version
):
    monkeypatch.setattr(gate, "version", lambda _: "2.8.0")
    with pytest.raises(SystemExit, match="Release blocked"):
        gate.require_release_dependencies(write_lock(tmp_path, version), installed=True)


@pytest.mark.parametrize("version", ["2.8.0", "2.8.1", "2.8.0.post1", "2.10.0", "3.0.0"])
def test_stable_patch_and_matching_artifacts_accepted(tmp_path, monkeypatch, version):
    monkeypatch.setattr(gate, "version", lambda _: version)
    gate.require_release_dependencies(
        write_lock(tmp_path, version),
        requirements=f"urllib3=={version} \\\n    --hash=sha256:{'a' * 64}\n",
        installed=True,
    )


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        "not toml",
        '[[package]]\nname = "other"\nversion = "2.8.0"\n',
        '[[package]]\nname = "urllib3"\n',
        '[[package]]\nname = "urllib3"\nversion = 2.8\n',
        '[[package]]\nname = "urllib3"\nversion = "2.8.0"\n' * 2,
    ],
)
def test_missing_invalid_or_ambiguous_lock_fails_closed(tmp_path, content):
    lock = tmp_path / "uv.lock"
    if content is not None:
        lock.write_text(content)
    with pytest.raises(SystemExit) as error:
        gate.require_release_dependencies(lock)
    assert str(error.value) == gate.RELEASE_HOLD


@pytest.mark.parametrize(
    "requirements",
    [
        "",
        "example==1.0\n",
        "urllib3==2.7.0\n",
        "urllib3==2.8.0rc1\n",
        "urllib3==2.8.1\n",
        "urllib3>=2.8.0\n",
        "urllib3==2.8.0\nurllib3==2.8.0\n",
        'urllib3==2.8.0; python_version < "3.0"\n',
        "urllib3 @ https://user:PRIVATE@example.invalid/wheel\n",
    ],
)
def test_missing_nonfinal_or_mismatched_package_pin_rejected(tmp_path, requirements):
    with pytest.raises(SystemExit) as error:
        gate.require_release_dependencies(write_lock(tmp_path, "2.8.0"), requirements=requirements)
    assert str(error.value) == gate.RELEASE_HOLD
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("installed", [None, "2.7.0", "2.8.0rc1", "2.8.1"])
def test_installed_build_dependency_must_exist_and_match_lock(tmp_path, monkeypatch, installed):
    def version(_):
        if installed is None:
            raise PackageNotFoundError
        return installed

    monkeypatch.setattr(gate, "version", version)
    with pytest.raises(SystemExit, match="Release blocked"):
        gate.require_release_dependencies(write_lock(tmp_path, "2.8.0"), installed=True)


def test_release_rejects_before_any_azd_or_azure_command(tmp_path, monkeypatch):
    release = importlib.import_module("release")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    write_cloud_lock(tmp_path, "2.7.0")
    monkeypatch.setattr(
        release, "run", lambda *_: pytest.fail("No release command may run before the gate")
    )
    monkeypatch.setattr(sys, "argv", ["release.py", "foundation", "--environment", "blocked"])
    with pytest.raises(SystemExit, match="Release blocked"):
        release.main()
    with pytest.raises(SystemExit, match="Release blocked"):
        release.update_existing(SimpleNamespace(), {}, tmp_path)


@pytest.mark.parametrize("with_runtime", [False, True])
def test_prepare_rejects_before_export_download_or_package_mutation(
    tmp_path, monkeypatch, with_runtime
):
    prepare = importlib.import_module("prepare_hosted")
    monkeypatch.setattr(prepare, "LANE_ROOT", tmp_path)
    monkeypatch.setattr(prepare, "AGENT_ROOT", tmp_path / "agent")
    write_cloud_lock(tmp_path, "2.7.0")
    monkeypatch.setattr(
        prepare.subprocess, "run", lambda *a, **kw: pytest.fail("No export/download allowed")
    )
    monkeypatch.setattr(
        sys, "argv", ["prepare_hosted.py", *(["--with-runtime"] if with_runtime else [])]
    )
    with pytest.raises(SystemExit, match="Release blocked"):
        prepare.main()
    assert not prepare.AGENT_ROOT.exists()
    with pytest.raises(SystemExit, match="Release blocked"):
        prepare.prepare_runtime()


def test_cloud_installed_mismatch_rejected_without_overwriting_package(tmp_path, monkeypatch):
    prepare = importlib.import_module("prepare_hosted")
    write_cloud_lock(tmp_path, "2.8.0")
    agent = tmp_path / "agent"
    agent.mkdir()
    requirements = agent / "requirements.txt"
    requirements.write_text("reviewed original")
    monkeypatch.setattr(prepare, "LANE_ROOT", tmp_path)
    monkeypatch.setattr(prepare, "AGENT_ROOT", agent)
    monkeypatch.setattr(sys, "argv", ["prepare_hosted.py"])
    monkeypatch.setattr(gate, "version", lambda _: "2.7.0")
    with pytest.raises(SystemExit, match="Release blocked"):
        prepare.main()
    assert requirements.read_text() == "reviewed original"


def test_verifier_rejects_packaged_mismatch_before_import_or_native_probe(tmp_path, monkeypatch):
    verify = importlib.import_module("verify_hosted_package")
    write_cloud_lock(tmp_path, "2.8.0")
    (tmp_path / "requirements.txt").write_text("urllib3==2.7.0\n")
    monkeypatch.setattr(verify, "LANE_ROOT", tmp_path)
    monkeypatch.setattr(verify, "AGENT_ROOT", tmp_path)
    monkeypatch.setattr(gate, "version", lambda _: "2.8.0")
    monkeypatch.setattr(sys, "argv", ["verify_hosted_package.py", "--require-runtime"])
    monkeypatch.setattr(
        verify.subprocess, "run", lambda *a, **kw: pytest.fail("No import/native probe allowed")
    )
    with pytest.raises(SystemExit, match="Release blocked"):
        verify.main()


def test_normal_azd_prepackage_stops_before_uv_sync_or_runtime_download(tmp_path):
    hook = (LANE / "azure.yaml").read_text().split("    run: |\n", 1)[1]
    hook = "\n".join(line.removeprefix("      ") for line in hook.splitlines())
    gate_command = "python3 scripts/verify_release_dependencies.py --lock requirements-cloud.lock"
    assert hook.index(gate_command) < hook.index(".venv-cloud/bin/python")
    assert "uv run" not in hook
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "verify_release_dependencies.py").write_bytes(
        (LANE / "scripts/verify_release_dependencies.py").read_bytes()
    )
    write_cloud_lock(tmp_path, "2.7.0")
    sentinel = tmp_path / "uv-called"
    # Shell function makes any attempt to reach uv observable without installing anything.
    command = f'uv() {{ touch "{sentinel}"; }}\n{hook}'
    result = subprocess.run(["sh", "-c", command], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    assert gate.RELEASE_HOLD in result.stderr
    assert not sentinel.exists()


def test_api_image_checks_lock_before_install_and_actual_venv_before_native_download():
    dockerfile = (LANE / "backend/Dockerfile").read_text()
    lock_check = "RUN python /build/verify_release_dependencies.py --lock "
    installed_check = (
        "/opt/venv/bin/python /build/verify_release_dependencies.py "
        "--lock requirements-cloud.lock --installed"
    )
    assert dockerfile.index(lock_check) < dockerfile.index("uv --no-config venv")
    assert dockerfile.index("uv --no-config pip install") < dockerfile.index(installed_check)
    assert dockerfile.index(installed_check) < dockerfile.index("download-runtime")


def test_cli_missing_requirements_is_fixed_actionable_error(tmp_path, monkeypatch, capsys):
    lock = write_lock(tmp_path, "2.8.0")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_dependencies.py",
            "--lock",
            str(lock),
            "--requirements",
            str(tmp_path / "missing"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        gate.main()
    assert str(error.value) == gate.RELEASE_HOLD
    assert not capsys.readouterr().out
