import argparse
import base64
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from checkout_recovery_copilot.application.ports import InvestigationIncompleteError

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
        "checkout.azurecr.io/checkout-recovery-copilot-api:latest",
        f"other.azurecr.io/checkout-recovery-copilot-api@sha256:{DIGEST}",
        f"checkout.azurecr.io/other@sha256:{DIGEST}",
        "checkout.azurecr.io/checkout-recovery-copilot-api@sha256:short",
    ],
)
def test_images_must_be_lane_owned_digests(image):
    with pytest.raises(SystemExit, match="lane-owned"):
        release.image_reference(image, REGISTRY, "checkout-recovery-copilot-api")


@pytest.mark.parametrize("group", ["maf", "rg-checkout-maf", "crcopilot/../other", ""])
def test_release_rejects_nonisolated_resource_groups(group):
    with pytest.raises(SystemExit, match="isolated crcopilot"):
        release.require_environment({"AZURE_RESOURCE_GROUP": group, "AZURE_SUBSCRIPTION_ID": "sub"})


def test_release_accepts_only_explicit_subscription():
    release.require_environment(
        {"AZURE_RESOURCE_GROUP": "rg-crcopilot-test", "AZURE_SUBSCRIPTION_ID": "sub"}
    )
    with pytest.raises(SystemExit, match="subscription"):
        release.require_environment({"AZURE_RESOURCE_GROUP": "rg-crcopilot-test"})


def test_release_rejects_existing_lane_project():
    with pytest.raises(SystemExit, match="outside the isolated release scope"):
        release.require_environment(
            {
                "AZURE_RESOURCE_GROUP": "rg-crcopilot-test",
                "AZURE_SUBSCRIPTION_ID": "sub",
                "AZURE_AI_PROJECT_ID": "/subscriptions/sub/resourceGroups/maf/providers/project",
            }
        )


def test_bootstrap_cannot_redeploy_existing_application_foundation(tmp_path):
    release.require_bootstrap(tmp_path)
    outputs = tmp_path / "app-outputs.json"
    outputs.write_text(json.dumps({"frontendUrl": {"value": ""}}))
    release.require_bootstrap(tmp_path)
    outputs.write_text(json.dumps({"frontendUrl": {"value": "https://owned.example"}}))
    with pytest.raises(SystemExit, match="update-existing"):
        release.require_bootstrap(tmp_path)


def test_manifest_source_allows_uncommitted_snapshot_and_detects_drift(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "source_manifest_test", Path(__file__).resolve().parents[2] / "scripts/source_manifest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = {"schema": 1, "source_sha256": "c" * 64, "files": {"source.py": "d" * 64}}
    monkeypatch.setattr(module, "snapshot", lambda: source)
    manifest = tmp_path / "source.json"
    manifest.write_text(json.dumps(source))
    assert module.verify(manifest) == "c" * 64
    source["files"]["source.py"] = "e" * 64
    with pytest.raises(SystemExit, match="changed"):
        module.verify(manifest)


def test_source_manifest_covers_ui_docker_e2e_copy_input():
    spec = importlib.util.spec_from_file_location(
        "source_manifest_docker", Path(__file__).resolve().parents[2] / "scripts/source_manifest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = "harness/checkout-recovery/copilot-sdk/frontend/e2e/checkout-recovery.spec.ts"
    files = module.snapshot()["files"]
    assert path in files
    assert "harness/checkout-recovery/copilot-sdk/frontend/.npmrc" in files
    assert "harness/checkout-recovery/copilot-sdk/scripts/verify_release_dependencies.py" in files


def test_ui_docker_loads_approved_registry_without_changing_tls():
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    config = (frontend / ".npmrc").read_text()
    dockerfile = (frontend / "Dockerfile").read_text()
    ignore = (frontend / "Dockerfile.dockerignore").read_text()
    assert "registry=https://packagefeedproxy.microsoft.io/npm/" in config.splitlines()
    assert "strict-ssl=false" not in config
    path = "harness/checkout-recovery/copilot-sdk/frontend/.npmrc"
    assert path in dockerfile
    assert "!" + path in ignore.splitlines()


def test_native_flag_does_not_accept_scripted_outcomes(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "checkout_e2e", Path(__file__).resolve().parents[2] / "scripts/e2e.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("sys.argv", ["e2e.py", "--require-copilot"])
    monkeypatch.setattr(
        module, "verify_case", lambda *args: {"actual": {"harness_mode": "scripted"}}
    )
    with pytest.raises(SystemExit, match="real Copilot"):
        module.main()


def test_failed_e2e_preserves_submitted_start_identity(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "checkout_failed_e2e", Path(__file__).resolve().parents[2] / "scripts/e2e.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "result.json"
    monkeypatch.setattr("sys.argv", ["e2e.py", "--output", str(output)])

    def fail(*args):
        raise SystemExit("Command failed")

    monkeypatch.setattr(module, "verify_case", fail)
    with pytest.raises(SystemExit, match="Command failed"):
        module.main()
    evidence = json.loads(output.read_text())
    assert evidence[0]["passed"] is False
    assert evidence[0]["request_id"]
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit, match="already exists"):
        module.main()


@pytest.fixture
def business_audit():
    spec = importlib.util.spec_from_file_location(
        "checkout_business_audit",
        Path(__file__).resolve().parents[2] / "scripts/verify_business.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scripted_audit_explicitly_skips_native_state_only(business_audit):
    assert business_audit.verify_harness({"harness_mode": "scripted"}, None, "scripted") is False
    with pytest.raises(AssertionError, match="harness mode"):
        business_audit.verify_harness({"harness_mode": "scripted"}, None, "copilot")
    with pytest.raises(AssertionError, match="harness mode"):
        business_audit.verify_harness({"harness_mode": "copilot"}, None, "scripted")


@pytest.fixture
def native_audit_state():
    identifier = "00000000-0000-0000-0000-000000000001"
    return {
        "format": "copilot-native-session-v1",
        "provenance": {
            "sdk_version": "1.0.13",
            "runtime_version": "1.0.85",
            "protocol_version": 3,
        },
        "sessions": {
            identifier: {
                "workspace.yaml": base64.b64encode(b"native").decode(),
                "events.jsonl": base64.b64encode(b'{"type":"session.start"}\n').decode(),
            }
        },
        "session_id": identifier,
        "workspace": {"plan.md": "Synthetic reviewed plan"},
        "evidence": {
            "native_skill_invoked": True,
            "native_skill_completed": True,
            "workspace_written": True,
            "workspace_read": True,
            "native_tools_completed": [
                "skill",
                "read_order",
                "read_payment",
                "read_inventory",
                "write_plan",
                "read_plan",
            ],
        },
    }


def test_native_audit_requires_archive_and_observed_plan(business_audit, native_audit_state):
    assert business_audit.verify_harness(
        {"harness_mode": "copilot"}, native_audit_state, "copilot"
    )
    native_audit_state["workspace"]["plan.md"] = ""
    with pytest.raises(AssertionError, match="plan"):
        business_audit.verify_harness({"harness_mode": "copilot"}, native_audit_state, "copilot")
    native_audit_state["format"] = "old-framework-state"
    with pytest.raises(InvestigationIncompleteError, match="native session archive"):
        business_audit.verify_harness({"harness_mode": "copilot"}, native_audit_state, "copilot")


@pytest.mark.parametrize(
    "missing",
    ["native_skill_invoked", "native_skill_completed", "workspace_written", "workspace_read"],
)
def test_native_audit_never_substitutes_claims_for_observed_evidence(
    business_audit, native_audit_state, missing
):
    native_audit_state["evidence"][missing] = False
    with pytest.raises(AssertionError, match="observed"):
        business_audit.verify_harness({"harness_mode": "copilot"}, native_audit_state, "copilot")


def test_native_audit_rejects_corrupt_archive_bytes(business_audit, native_audit_state):
    identifier = native_audit_state["session_id"]
    native_audit_state["sessions"][identifier]["workspace.yaml"] = "not-base64!"
    with pytest.raises(InvestigationIncompleteError, match="native session archive"):
        business_audit.verify_harness({"harness_mode": "copilot"}, native_audit_state, "copilot")


def test_native_audit_rejects_missing_archive_despite_workspace_claim(business_audit):
    with pytest.raises(InvestigationIncompleteError, match="native session archive"):
        business_audit.verify_harness(
            {"harness_mode": "copilot"}, {"workspace": {"plan.md": "claimed"}}, "copilot"
        )


def test_native_audit_uses_sdk_validator(business_audit, native_audit_state, monkeypatch):
    from checkout_recovery_copilot.sdk import archive

    original = archive.validate
    calls = []

    def validate(state):
        calls.append(state)
        return original(state)

    monkeypatch.setattr(archive, "validate", validate)
    before = deepcopy(native_audit_state)
    assert business_audit.verify_harness(
        {"harness_mode": "copilot"}, native_audit_state, "copilot"
    )
    assert calls == [before]
    assert native_audit_state == before


def test_native_audit_requires_primary_session(business_audit, native_audit_state):
    native_audit_state["session_id"] = "00000000-0000-0000-0000-000000000002"
    with pytest.raises(AssertionError, match="Primary native session"):
        business_audit.verify_harness({"harness_mode": "copilot"}, native_audit_state, "copilot")


@pytest.mark.parametrize("filename", ["events.jsonl", "workspace.yaml"])
@pytest.mark.parametrize("missing", [True, False])
def test_native_audit_requires_nonempty_primary_files(
    business_audit, native_audit_state, filename, missing
):
    files = native_audit_state["sessions"][native_audit_state["session_id"]]
    if missing:
        del files[filename]
    else:
        files[filename] = ""
    with pytest.raises(AssertionError, match="nonempty events or workspace"):
        business_audit.verify_harness({"harness_mode": "copilot"}, native_audit_state, "copilot")


@pytest.mark.parametrize("plan", ["x" * 8192, "é" * 4096])
def test_native_audit_accepts_plan_at_byte_limit(business_audit, native_audit_state, plan):
    native_audit_state["workspace"]["plan.md"] = plan
    assert business_audit.verify_harness(
        {"harness_mode": "copilot"}, native_audit_state, "copilot"
    )


@pytest.mark.parametrize("plan", ["x" * 8193, "é" * 4097])
def test_native_audit_limits_plan_bytes_not_characters(business_audit, native_audit_state, plan):
    native_audit_state["workspace"]["plan.md"] = plan
    with pytest.raises(AssertionError, match="oversized"):
        business_audit.verify_harness({"harness_mode": "copilot"}, native_audit_state, "copilot")


@pytest.mark.parametrize(
    "tool", ["skill", "read_order", "read_payment", "read_inventory", "write_plan", "read_plan"]
)
def test_native_audit_requires_every_native_tool_completion(
    business_audit, native_audit_state, tool
):
    native_audit_state["evidence"]["native_tools_completed"].remove(tool)
    with pytest.raises(AssertionError, match="Required native tool completions"):
        business_audit.verify_harness({"harness_mode": "copilot"}, native_audit_state, "copilot")


@pytest.mark.parametrize("completed", [None, "skill", [{}]])
def test_native_audit_rejects_malformed_completions(
    business_audit, native_audit_state, completed
):
    native_audit_state["evidence"]["native_tools_completed"] = completed
    with pytest.raises(AssertionError, match="Required native tool completions"):
        business_audit.verify_harness({"harness_mode": "copilot"}, native_audit_state, "copilot")


@pytest.mark.parametrize("head,dirty", [("c" * 40, ""), (COMMIT, " M tracked.py")])
def test_source_must_be_exact_and_clean(monkeypatch, head, dirty):
    monkeypatch.setattr(release, "run", lambda command: head if "rev-parse" in command else dirty)
    with pytest.raises(SystemExit):
        release.require_source(COMMIT)


@pytest.mark.parametrize("value", [None, ""])
def test_secret_reference_empty_value_serialization_is_equivalent(value):
    before = {
        "properties": {
            "managedEnvironmentId": "environment",
            "configuration": {},
            "template": {"containers": [{"env": [{"name": "TOKEN", "secretRef": "token"}]}]},
        }
    }
    after = deepcopy(before)
    variable = after["properties"]["template"]["containers"][0]["env"][0]
    variable["value"] = value
    assert release.stable_app(before) == release.stable_app(after)
    variable["secretRef"] = "different-token"
    assert release.stable_app(before) != release.stable_app(after)
    variable["secretRef"] = "token"
    variable["value"] = "unexpected-literal"
    assert release.stable_app(before) != release.stable_app(after)


@pytest.fixture
def guarded_update(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "ROOT", tmp_path)
    (tmp_path / "requirements-cloud.lock").write_text(
        f"urllib3==2.8.0 --hash=sha256:{'a' * 64}\n"
    )
    monkeypatch.setattr("verify_release_dependencies.version", lambda _: "2.8.0")
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
        backend_image=f"{REGISTRY}/checkout-recovery-copilot-api@sha256:{DIGEST}",
        frontend_image=f"{REGISTRY}/checkout-recovery-copilot-web@sha256:{DIGEST}",
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
            "checkout-recovery-copilot",
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
