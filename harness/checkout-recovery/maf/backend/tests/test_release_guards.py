import argparse
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "checkout_release", Path(__file__).resolve().parents[2] / "scripts/release.py"
)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
COMMIT = "a" * 40
REGISTRY = "checkout.azurecr.io"
DIGEST = "b" * 64


@pytest.mark.parametrize(
    "image",
    [
        "checkout.azurecr.io/checkout-recovery-maf-api:latest",
        f"other.azurecr.io/checkout-recovery-maf-api@sha256:{DIGEST}",
        f"checkout.azurecr.io/other@sha256:{DIGEST}",
        "checkout.azurecr.io/checkout-recovery-maf-api@sha256:short",
    ],
)
def test_images_must_be_lane_owned_digests(image):
    with pytest.raises(SystemExit, match="lane-owned"):
        release.image_reference(image, REGISTRY, "checkout-recovery-maf-api")


@pytest.mark.parametrize("head,dirty", [("c" * 40, ""), (COMMIT, " M tracked.py")])
def test_source_must_be_exact_and_clean(monkeypatch, head, dirty):
    monkeypatch.setattr(release, "run", lambda command: head if "rev-parse" in command else dirty)
    with pytest.raises(SystemExit):
        release.require_source(COMMIT)


@pytest.fixture
def guarded_update(tmp_path, monkeypatch):
    env = {"AZURE_SUBSCRIPTION_ID": "sub", "AZURE_RESOURCE_GROUP": "checkout-group"}
    outputs = {
        "registryLoginServer": {"value": REGISTRY},
        "registryName": {"value": "checkout"},
        "backendAppName": {"value": "checkout-api"},
        "frontendAppName": {"value": "checkout-web"},
    }
    (tmp_path / "app-outputs.json").write_text(json.dumps(outputs))
    args = argparse.Namespace(
        source_commit=COMMIT,
        output_dir=tmp_path / "receipt",
        apply=False,
        backend_image=f"{REGISTRY}/checkout-recovery-maf-api@sha256:{DIGEST}",
        frontend_image=f"{REGISTRY}/checkout-recovery-maf-web@sha256:{DIGEST}",
    )
    apps = {}
    for name, container in (("checkout-api", "backend"), ("checkout-web", "frontend")):
        apps[name] = {
            "id": (
                "/subscriptions/sub/resourceGroups/checkout-group"
                f"/providers/Microsoft.App/containerApps/{name}"
            ),
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {"identity-id": {}}},
            "properties": {
                "managedEnvironmentId": "existing-environment",
                "configuration": {"ingress": {"external": container == "frontend"}},
                "template": {
                    "containers": [
                        {
                            "name": container,
                            "image": "old@sha256:old",
                            "env": [{"name": "TOKEN", "secretRef": "token"}],
                        }
                    ]
                },
                "latestRevisionName": name + "--old",
                "latestReadyRevisionName": name + "--old",
            },
        }
    calls = []

    def run(command):
        calls.append(command)
        if command[0] == "git":
            return COMMIT if "rev-parse" in command else ""
        assert "--subscription" in command
        if command[1:3] == ["acr", "repository"]:
            return json.dumps(
                {
                    "digest": "sha256:" + DIGEST,
                    "tags": [COMMIT + "-build"],
                    "changeableAttributes": {"writeEnabled": False, "deleteEnabled": False},
                }
            )
        name = command[command.index("-n") + 1]
        if command[1:4] == ["containerapp", "revision", "show"]:
            return json.dumps({"properties": {"healthState": "Healthy", "active": True}})
        if command[1:3] == ["containerapp", "update"]:
            app = apps[name]["properties"]
            app["template"]["containers"][0]["image"] = command[command.index("--image") + 1]
            app["latestRevisionName"] = name + "--new"
            app["latestReadyRevisionName"] = name + "--new"
        else:
            assert command[1:3] == ["containerapp", "show"]
        return json.dumps(apps[name])

    monkeypatch.setattr(release, "run", run)
    return args, env, apps, calls, run


def test_preview_is_read_only_and_exclusive(guarded_update, tmp_path):
    args, env, _, calls, _ = guarded_update
    release.update_existing(args, env, tmp_path)
    assert not any("update" in command for command in calls)
    assert (args.output_dir / "update-preview.json").exists()
    with pytest.raises(SystemExit, match="already exists"):
        release.update_existing(args, env, tmp_path)


def test_apply_only_updates_two_images_and_locks_both_scopes(guarded_update, tmp_path):
    args, env, apps, calls, _ = guarded_update
    original = deepcopy(apps)
    release.update_existing(args, env, tmp_path)
    args.apply = True
    release.update_existing(args, env, tmp_path)
    updates = [command for command in calls if command[1:3] == ["containerapp", "update"]]
    assert len(updates) == 2
    assert (
        len([command for command in calls if command[1:4] == ["acr", "repository", "update"]]) == 4
    )
    assert not any("deployment" in command or "provision" in command for command in calls)
    for name, before in original.items():
        assert release.stable_app(apps[name]) == release.stable_app(before)
    assert json.loads((args.output_dir / "update-completed.json").read_text())["passed"] is True


def test_post_update_configuration_drift_fails(guarded_update, tmp_path, monkeypatch):
    args, env, apps, _, original_run = guarded_update
    release.update_existing(args, env, tmp_path)
    args.apply = True

    def run(command):
        result = original_run(command)
        if command[1:3] == ["containerapp", "update"]:
            apps["checkout-api"]["properties"]["configuration"]["ingress"]["external"] = True
        return result

    monkeypatch.setattr(release, "run", run)
    with pytest.raises(SystemExit, match="other than its image"):
        release.update_existing(args, env, tmp_path)
    assert not (args.output_dir / "update-completed.json").exists()


def test_bad_image_source_tag_prevents_all_mutation(guarded_update, tmp_path, monkeypatch):
    args, env, _, calls, original_run = guarded_update
    release.update_existing(args, env, tmp_path)
    args.apply = True

    def run(command):
        result = original_run(command)
        if command[1:4] == ["acr", "repository", "show"]:
            value = json.loads(result)
            value["tags"] = ["unrelated"]
            return json.dumps(value)
        return result

    monkeypatch.setattr(release, "run", run)
    with pytest.raises(SystemExit, match="source-commit tag"):
        release.update_existing(args, env, tmp_path)
    assert not any("update" in command for command in calls)


def test_apply_requires_saved_preview(guarded_update, tmp_path):
    args, env, _, calls, _ = guarded_update
    args.apply = True
    with pytest.raises(SystemExit, match="saved preview"):
        release.update_existing(args, env, tmp_path)
    assert not any("update" in command for command in calls)


def test_apply_rejects_drift_since_actual_preview(guarded_update, tmp_path):
    args, env, apps, calls, _ = guarded_update
    release.update_existing(args, env, tmp_path)
    apps["checkout-api"]["properties"]["configuration"]["ingress"]["external"] = True
    args.apply = True
    with pytest.raises(SystemExit, match="changed since the saved preview"):
        release.update_existing(args, env, tmp_path)
    assert not any("update" in command for command in calls)


def test_final_readback_rechecks_backend_after_frontend_update(
    guarded_update, tmp_path, monkeypatch
):
    args, env, apps, _, original_run = guarded_update
    release.update_existing(args, env, tmp_path)
    args.apply = True

    def run(command):
        result = original_run(command)
        if command[1:3] == ["containerapp", "update"] and "checkout-web" in command:
            apps["checkout-api"]["properties"]["template"]["containers"][0]["image"] = "other"
        return result

    monkeypatch.setattr(release, "run", run)
    with pytest.raises(SystemExit, match="differs from the approved image"):
        release.update_existing(args, env, tmp_path)
    assert not (args.output_dir / "update-completed.json").exists()


def test_hosted_mismatch_retains_response_and_start_identity(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "checkout_verify_hosted", Path(__file__).resolve().parents[2] / "scripts/verify_hosted.py"
    )
    assert spec and spec.loader
    hosted = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hosted)
    output = tmp_path / "smoke.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_hosted.py",
            "--environment",
            "test",
            "--agent-name",
            "checkout-recovery-maf",
            "--version",
            "3",
            "--smoke",
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(hosted, "run_azd", lambda command: "{}")
    failed = {
        "case_id": "failed-case",
        "failure_code": "harness_failed",
        "terminal_status": "failed",
        "diagnostic_disposition": None,
    }
    monkeypatch.setattr(hosted, "invoke", lambda *args: failed)
    with pytest.raises(hosted.HostedVerificationError, match="Outcome mismatch"):
        hosted.main()
    assert json.loads(output.read_text())[0] == {
        "fixture_id": "recoverable-inventory-reservation",
        "passed": False,
        "actual": failed,
    }
    journal = json.loads(output.with_name("smoke-commands.json").read_text())
    assert journal["version"] == "3"
    assert journal["commands"][0]["result"] == failed
    assert journal["commands"][0]["command"]["request_id"]
    assert output.stat().st_mode & 0o777 == 0o600
