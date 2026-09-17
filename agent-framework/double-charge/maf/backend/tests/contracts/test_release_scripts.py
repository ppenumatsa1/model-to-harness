from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tomllib
import zipfile
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

LANE = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "azure.yaml").exists()
)
SCRIPTS = LANE / "scripts"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import bind_hosted_eval
    import e2e
    import hosted_harness
    import release

    return release, hosted_harness, bind_hosted_eval, e2e


def test_azd_json_is_data_not_shell_program(modules):
    release, *_ = modules
    runner = Mock()
    literal = '$(touch forbidden); "quote"; `false`; ${SHELL}'
    runner.json.return_value = {"DATABASE_URL": literal}
    assert release.environment_values(runner, "maf-dev") == {"DATABASE_URL": literal}
    assert runner.json.call_args.args[0] == [
        "azd",
        "env",
        "get-values",
        "--output",
        "json",
        "--environment",
        "maf-dev",
    ]
    runner.json.return_value = {"NOT_STRING": {"nested": True}}
    with pytest.raises(release.ReleaseError):
        release.environment_values(runner, "maf-dev")


def test_parameter_credentials_restricted_and_removed_even_on_error(modules):
    release, *_ = modules
    with release.private_workspace(LANE / ".azure" / "test-release") as directory:
        with pytest.raises(RuntimeError, match="intentional"):
            with release.parameter_file(directory, {"password": 'a"$(echo bad)\\b'}) as path:
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
                assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
                assert json.loads(path.read_text())["parameters"]["password"]["value"] == (
                    'a"$(echo bad)\\b'
                )
                raise RuntimeError("intentional")
        assert not path.exists()
        assert not list(directory.iterdir())


def test_schema_rejects_reuse_and_other_lane(modules):
    release, *_ = modules
    assert release.validate_schema("maf_double_charge_cutover", "maf_double_charge")
    for schema in (
        "maf_double_charge",
        "public",
        "langgraph_double_charge",
        "maf_x;DROP",
        "maf_" * 30,
    ):
        with pytest.raises(release.ReleaseError):
            release.validate_schema(schema, "maf_double_charge")


def test_pending_hosted_versions_are_not_success(modules):
    release, *_ = modules
    for status in ("pending", "running", "error", "failed", ""):
        with pytest.raises(release.ReleaseError):
            release.active_agent({"status": status, "version": "4"})
    assert release.active_agent({"status": "active", "version": "4"}) == "4"


@pytest.mark.parametrize("version", ["5", "6"])
def test_hosted_wait_verifies_source_even_when_version_is_reused(modules, monkeypatch, version):
    release, *_ = modules
    runner = Mock()
    runner.json.return_value = {"status": "active", "version": version}
    subject = release.Release(release.parser().parse_args([]), runner)
    subject.old_version = "5"
    verify = Mock()
    monkeypatch.setattr(subject, "verify_hosted_source", verify)
    assert subject.wait_hosted() == version
    verify.assert_called_once_with(version)
    verify.side_effect = release.ReleaseError("source mismatch")
    with pytest.raises(release.ReleaseError, match="source mismatch"):
        subject.wait_hosted()


@pytest.mark.parametrize(
    "mismatch",
    [None, "hash", "source", "missing", ".env", ".foundry/result.json", "extra.py", "duplicate"],
)
def test_hosted_archive_requires_exact_prepared_source(modules, tmp_path, mismatch):
    release, *_ = modules
    names = [
        "main.py",
        "requirements.txt",
        "maf_double_charge/__init__.py",
        "model_to_harness_shared/__init__.py",
    ]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            if mismatch != "missing" or name != "main.py":
                archive.writestr(name, name)
        if mismatch in {".env", ".foundry/result.json", "extra.py"}:
            archive.writestr(mismatch, "excluded")
        if mismatch == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("main.py", "main.py")
        archive.writestr(".agentignore", ".env")
    content = buffer.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    if mismatch == "hash":
        digest = "0" * 64
    if mismatch == "source":
        (tmp_path / "main.py").write_text("changed")
    if mismatch:
        with pytest.raises(release.ReleaseError):
            release.verify_code_archive(tmp_path, content, digest)
    else:
        assert release.verify_code_archive(tmp_path, content, f"sha256:{digest}") == digest


def test_existing_update_requires_the_current_maf_schema(modules):
    release, *_ = modules
    schema = release.SCHEMA
    assert release.validate_schema(schema, schema, update_existing=True) == schema
    for requested in ("maf_other", "public", "langgraph_double_charge"):
        with pytest.raises(release.ReleaseError):
            release.validate_schema(requested, schema, update_existing=True)


@pytest.mark.parametrize("invalid_history", [False, True])
def test_existing_schema_check_is_read_only_and_fails_closed(modules, monkeypatch, invalid_history):
    from maf_double_charge.application.errors import SchemaVersionError

    release, *_ = modules
    connection = AsyncMock()
    connection.__aenter__.return_value = connection
    connect = AsyncMock(return_value=connection)
    check = AsyncMock(
        side_effect=SchemaVersionError("private database details") if invalid_history else None
    )
    monkeypatch.setattr("psycopg.AsyncConnection.connect", connect)
    monkeypatch.setattr(
        "maf_double_charge.infrastructure.persistence.migrations.check_schema", check
    )
    subject = release.Release(release.parser().parse_args(["--update-existing"]))
    subject.database_url = "private-connection"
    subject.schema = release.SCHEMA
    if invalid_history:
        with pytest.raises(release.ReleaseError, match="schema verification failed") as error:
            subject.verify_existing_schema()
        assert "private" not in str(error.value)
    else:
        subject.verify_existing_schema()
    connection.execute.assert_awaited_once_with("SET TRANSACTION READ ONLY")
    check.assert_awaited_once_with(
        connection, release.SCHEMA, migrations_dir=LANE / "backend/migrations"
    )
    connection.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("preview", [True, False])
def test_arm_output_uses_machine_json_without_pretty_print_for_preview(modules, tmp_path, preview):
    release, *_ = modules
    runner = Mock()
    runner.json.return_value = {
        "status": "Succeeded",
        "changes": [],
        "properties": {"provisioningState": "Succeeded"},
    }
    subject = release.Release(release.parser().parse_args([]), runner)
    subject.subscription = "subscription"
    subject.group = "group"
    subject.workspace = tmp_path
    subject.deploy_parameters({}, preview=preview)
    arguments = runner.json.call_args.args[0]
    assert ("--no-pretty-print" in arguments) is preview
    assert arguments[arguments.index("-o") + 1] == "json"
    if preview:
        assert arguments[arguments.index("--result-format") + 1] == "FullResourcePayloads"


@pytest.mark.parametrize(
    "result", [{}, {"status": "Succeeded"}, {"status": "Succeeded", "changes": {}}]
)
def test_preview_rejects_incomplete_arm_result(modules, tmp_path, result):
    release, *_ = modules
    runner = Mock()
    runner.json.return_value = result
    subject = release.Release(release.parser().parse_args([]), runner)
    subject.subscription = "subscription"
    subject.group = "group"
    subject.workspace = tmp_path
    with pytest.raises(release.ReleaseError, match="what-if"):
        subject.deploy_parameters({}, preview=True)


def test_subprocess_failures_never_reveal_credentials(modules, monkeypatch):
    release, *_ = modules
    invoke = Mock(return_value=Mock(returncode=1, stdout="password-secret", stderr="token-secret"))
    monkeypatch.setattr(release.subprocess, "run", invoke)
    with pytest.raises(release.ReleaseError) as failure:
        release.Runner().run(["az", "deployment", "group", "show"])
    assert "secret" not in str(failure.value)
    assert invoke.call_args.kwargs["capture_output"] is True
    assert "shell" not in invoke.call_args.kwargs


def test_discovery_preserves_existing_target_and_reports_stopped_postgres(modules):
    release, *_ = modules
    project_id = (
        "/subscriptions/sub/resourceGroups/group/providers/"
        "Microsoft.CognitiveServices/accounts/account/projects/project"
    )
    values = {
        "AZURE_SUBSCRIPTION_ID": "sub",
        "AZURE_RESOURCE_GROUP": "group",
        "AZURE_LOCATION": "northcentralus",
        "AZURE_AI_PROJECT_ID": project_id,
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": "existing-model",
        "AGENT_MODEL_HARNESS_MAF_INSTANCE_IDENTITY_PRINCIPAL_ID": "hosted-principal",
        "FOUNDRY_PROJECT_ENDPOINT": "https://existing-project",
        "DATABASE_URL": "postgresql://admin:p%40ss@existing.postgres.database.azure.com/db",
        "POSTGRES_ADMIN_PASSWORD": "p@ss",
    }
    deployment = {
        "properties": {
            "provisioningState": "Succeeded",
            "parameters": {
                "namePrefix": {"value": "existing"},
                "operatorIp": {"value": "192.0.2.1"},
            },
            "outputs": {
                key: {"value": value}
                for key, value in {
                    "backendName": "api",
                    "frontendName": "web",
                    "registryName": "registry",
                    "postgresHost": "existing.postgres.database.azure.com",
                }.items()
            },
        }
    }
    backend = {
        "properties": {
            "template": {
                "containers": [
                    {
                        "image": "registry/existing-api:old",
                        "env": [{"name": "DATABASE_SCHEMA", "value": "maf_old"}],
                    }
                ]
            },
            "configuration": {"ingress": {"external": False, "targetPort": 8010}},
        }
    }
    frontend = {"properties": {"template": {"containers": [{"image": "registry/web:old"}]}}}
    runner = Mock()
    runner.json.side_effect = [
        values,
        deployment,
        backend,
        frontend,
        {"loginServer": "registry.azurecr.io"},
        {"identity": {"principalId": "project-principal"}},
        {"status": "active", "version": "3"},
        {"state": "Stopped"},
    ]
    subject = release.Release(release.parser().parse_args([]), runner)
    subject.discover()
    assert subject.parameters["backendImage"] == "registry/existing-api:old"
    assert subject.parameters["postgresSchema"] == "maf_old"
    assert subject.parameters["postgresServerName"] == "existing"
    assert subject.parameters["postgresAdministratorPassword"] == "p@ss"
    assert subject.parameters["namePrefix"] == "existing"
    assert subject.postgres_state == "Stopped"
    assert subject.schema == release.SCHEMA
    runner.run.assert_not_called()
    for call in runner.json.call_args_list:
        assert not {"create", "deploy", "provision", "start", "set"} & set(call.args[0])


@pytest.mark.parametrize("app_only", [False, True])
def test_apply_rejects_dirty_commit(modules, app_only):
    release, *_ = modules
    args = release.parser().parse_args(
        ["--apply", "--source-commit", "a" * 40]
        + (["--app-only", "--update-existing"] if app_only else [])
    )
    runner = Mock()
    runner.run.side_effect = ["a" * 40, "a" * 40, " M backend/runtime.py"]
    with pytest.raises(release.ReleaseError):
        release.Release(args, runner).source_commit()


def app_only_fixture(release):
    apps = {}
    for kind in ("backend", "frontend"):
        name = f"maf-{kind}"
        identifier = (
            f"/subscriptions/sub/resourceGroups/maf-only/providers/Microsoft.App/containerApps/{name}"
        )
        props = {
            "managedEnvironmentId": "/existing-environment",
            "environmentId": "/existing-environment",
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "external": kind == "frontend", "targetPort": 8010 if kind == "backend" else 80,
                    "transport": "auto", "exposedPort": 0,
                    "traffic": [{"latestRevision": True, "weight": 100}],
                },
                "registries": [{"server": "registry.azurecr.io", "identity": "/existing-identity"}],
            },
            "template": {
                "containers": [{
                    "name": kind, "image": f"registry.azurecr.io/model-harness-maf-{kind}:old",
                    "env": [{"name": "DATABASE_SCHEMA", "value": release.SCHEMA}],
                    "resources": {"cpu": 0.5, "memory": "1Gi"},
                }],
                "scale": {"minReplicas": 1, "maxReplicas": 2},
            },
        }
        if kind == "backend":
            props["configuration"]["secrets"] = [{"name": "database-url", "value": "private-old"}]
        apps[identifier.lower()] = {
            "id": identifier, "name": name, "location": "northcentralus",
            "type": "Microsoft.App/containerApps",
            "identity": {
                "type": "UserAssigned", "userAssignedIdentities": {"/existing-identity": {}},
            },
            "properties": props,
        }
    baseline = {identifier: release.app_spec(app) for identifier, app in apps.items()}
    return apps, baseline


def app_only_preview(apps, desired):
    changes = []
    for identifier, app in apps.items():
        before = deepcopy(app)
        after = deepcopy(app)
        after["properties"]["template"]["containers"][0]["image"] = (
            desired[identifier]["properties"]["template"]["containers"][0]["image"]
        )
        for resource in (before, after):
            for secret in resource["properties"]["configuration"].get("secrets", []):
                secret["value"] = "**********"
        changed = before != after
        changes.append({
            "resourceId": identifier, "changeType": "Modify" if changed else "NoChange",
            "before": before, "after": after,
            "delta": [{"path": "properties.template.containers", "propertyChangeType": "Array"}]
            if changed else [],
        })
    return {"status": "Succeeded", "changes": changes}


@pytest.mark.parametrize("rollout", [False, True])
def test_app_only_full_preview_preserves_everything_but_images(modules, rollout):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    desired = deepcopy(baseline)
    if rollout:
        for spec in desired.values():
            spec["properties"]["template"]["containers"][0]["image"] += "-new"
    preview = app_only_preview(apps, desired)
    preview["changes"].append({
        "resourceId": "/untouched/foundation", "changeType": "Ignore",
        "before": {"id": "/untouched/foundation"}, "after": {"id": "/untouched/foundation"},
    })
    release.app_only_what_if(preview, baseline, desired)


@pytest.mark.parametrize("invalid", [
    "foundation-modify", "foundation-delete", "foundation-ignore-delta", "managed-ignore",
    "missing-app", "duplicate", "missing-before", "wrong-id", "failed", "diagnostic",
    "environment", "identity", "traffic", "secret", "schema", "scale", "extra-property",
    "wrong-image", "unknown-delta", "nondefault-running", "unexpected-default-change",
])
def test_app_only_preview_rejects_unapproved_full_resource_changes(modules, invalid):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    desired = deepcopy(baseline)
    preview = app_only_preview(apps, desired)
    change = preview["changes"][0]
    after = change["after"]
    if invalid.startswith("foundation"):
        unmanaged = {
            "resourceId": "/unmanaged", "changeType": "Modify",
            "before": {"id": "/unmanaged", "sharing": False},
            "after": {"id": "/unmanaged", "sharing": True},
        }
        if invalid == "foundation-delete":
            unmanaged["changeType"] = "Delete"
        elif invalid == "foundation-ignore-delta":
            unmanaged["changeType"] = "Ignore"
            unmanaged["after"] = deepcopy(unmanaged["before"])
            unmanaged["delta"] = [{"path": "sharing"}]
        preview["changes"].append(unmanaged)
    elif invalid == "managed-ignore":
        change["changeType"] = "Ignore"
    elif invalid == "missing-app":
        preview["changes"].pop()
    elif invalid == "duplicate":
        preview["changes"].append(deepcopy(change))
    elif invalid == "missing-before":
        change.pop("before")
    elif invalid == "wrong-id":
        after["id"] = "/different-app"
    elif invalid == "failed":
        preview["status"] = "Failed"
    elif invalid == "diagnostic":
        change["diagnostics"] = [{"message": "cannot evaluate"}]
    else:
        change["changeType"] = "Modify"
        change["delta"] = [{"path": "properties.template.containers"}]
        if invalid == "environment":
            after["properties"]["managedEnvironmentId"] = "/another-environment"
        elif invalid == "identity":
            after["identity"]["userAssignedIdentities"] = {"/another-identity": {}}
        elif invalid == "traffic":
            after["properties"]["configuration"]["ingress"]["external"] = True
        elif invalid == "secret":
            after["properties"]["configuration"]["secrets"][0]["value"] = "changed-private"
        elif invalid == "schema":
            after["properties"]["template"]["containers"][0]["env"][0]["value"] = "maf_other"
        elif invalid == "scale":
            after["properties"]["template"]["scale"]["maxReplicas"] = 20
        elif invalid == "extra-property":
            after["properties"]["unknownSetting"] = True
        elif invalid == "wrong-image":
            after["properties"]["template"]["containers"][0]["image"] = "unreviewed"
        elif invalid == "unknown-delta":
            change["delta"] = [{"path": "properties.configuration.secrets"}]
        elif invalid == "nondefault-running":
            change["before"]["properties"]["runningStatus"] = "Stopped"
        elif invalid == "unexpected-default-change":
            change["before"]["properties"]["configuration"]["ingress"]["exposedPort"] = 1234
            after["properties"]["configuration"]["ingress"].pop("exposedPort")
    with pytest.raises(release.ReleaseError):
        release.app_only_what_if(preview, baseline, desired)


def test_app_only_accepts_only_observed_service_default_omissions(modules):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    preview = app_only_preview(apps, baseline)
    for change in preview["changes"]:
        change["before"]["properties"]["runningStatus"] = "Running"
        change["after"]["properties"]["configuration"]["ingress"].pop("exposedPort")
        change["changeType"] = "Modify"
        change["delta"] = [
            {"path": "properties.runningStatus"},
            {"path": "properties.configuration.ingress.exposedPort"},
        ]
    release.app_only_what_if(preview, baseline, baseline)


@pytest.mark.parametrize("arguments", [
    ["--app-only"], ["--app-only", "--update-existing", "--foundation"],
    ["--app-only", "--update-existing", "--operator-ip", "192.0.2.1"],
])
def test_app_only_invalid_mode_stops_before_discovery(modules, arguments):
    release, *_ = modules
    runner = Mock()
    with pytest.raises(release.ReleaseError, match="requires --update-existing"):
        release.Release(release.parser().parse_args(arguments), runner).execute()
    runner.run.assert_not_called()
    runner.json.assert_not_called()


@pytest.mark.parametrize("apply", [False, True])
def test_app_only_orders_gates_without_foundation_or_migration(modules, monkeypatch, apply):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    subject = release.Release(release.parser().parse_args(
        ["--app-only", "--update-existing"]
        + (["--apply", "--source-commit", "a" * 40] if apply else [])
    ))
    subject.backend, subject.frontend = list(apps.values())
    subject.app_baseline = baseline
    subject.schema = release.SCHEMA
    subject.dirty = False
    subject.registry_server = "registry.azurecr.io"
    subject.parameters = {"postgresSchema": release.SCHEMA}
    operations = []
    monkeypatch.setattr(subject, "source_commit", lambda: operations.append("source") or "a" * 40)
    monkeypatch.setattr(subject, "discover", lambda: operations.append("discover"))
    monkeypatch.setattr(subject, "verify_existing_schema", lambda: operations.append("schema"))
    monkeypatch.setattr(
        subject, "deploy_parameters", Mock(side_effect=AssertionError("foundation"))
    )
    monkeypatch.setattr(
        subject, "deploy_hosted", lambda: operations.append("hosted-verified") or "9"
    )
    monkeypatch.setattr(subject, "wait_apps", lambda _: operations.append("ready"))
    monkeypatch.setattr(subject, "verify_app_state", lambda _: operations.append("readback"))

    def build(*_):
        operations.append("build")
        return {
            kind + "Image": f"registry.azurecr.io/model-harness-maf-{kind}@sha256:" + "a" * 64
            for kind in ("backend", "frontend")
        }

    def deploy(specs, *, preview):
        operations.append("preview" if preview else "rollout")
        return app_only_preview(apps, specs)

    monkeypatch.setattr(subject, "build", build)
    monkeypatch.setattr(subject, "deploy_apps_only", deploy)
    subject.execute()
    assert operations == (
        ["source", "discover", "schema", "preview"]
        + (["build", "source", "preview", "readback", "source", "rollout", "ready",
            "readback", "hosted-verified"] if apply else [])
    )


def test_app_only_uses_separate_incremental_template_and_private_parameters(
    modules, tmp_path, capsys
):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    runner = Mock()
    runner.json.return_value = app_only_preview(apps, baseline)
    subject = release.Release(
        release.parser().parse_args(["--app-only", "--update-existing"]), runner
    )
    subject.backend, subject.frontend = list(apps.values())
    subject.group, subject.subscription = "group", "subscription"
    subject.workspace = tmp_path
    subject.deploy_apps_only(baseline, preview=True)
    command = runner.json.call_args.args[0]
    assert command[command.index("--name") + 1] == release.APP_UPDATE_DEPLOYMENT
    assert command[command.index("--template-file") + 1].endswith("/update-existing.bicep")
    assert command[command.index("--mode") + 1] == "Incremental"
    assert "--no-pretty-print" in command
    assert command[command.index("--validation-level") + 1] == "Provider"
    assert "private-old" not in " ".join(command)
    assert "private-old" not in capsys.readouterr().out
    receipts = list(tmp_path.glob("app-only-what-if-*.json"))
    assert len(receipts) == 1 and stat.S_IMODE(receipts[0].stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*/parameters.json"))


def test_app_only_secret_drift_prevents_rollout(modules, monkeypatch):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    subject = release.Release(release.parser().parse_args(["--app-only", "--update-existing"]))
    subject.backend, subject.frontend = list(apps.values())
    monkeypatch.setattr(subject, "app", lambda _: {})
    changed = deepcopy(next(iter(baseline.values())))
    changed["properties"]["configuration"]["secrets"][0]["value"] = "new-private"
    monkeypatch.setattr(subject, "read_app_spec", lambda _: changed)
    with pytest.raises(release.ReleaseError, match="secrets drifted"):
        subject.verify_app_state(baseline)


def test_app_only_rejects_non_image_change_even_when_desired_snapshot_matches(modules):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    desired = deepcopy(baseline)
    identifier = next(iter(desired))
    desired[identifier]["properties"]["configuration"]["ingress"]["external"] = True
    preview = app_only_preview(apps, desired)
    change = preview["changes"][0]
    change["after"]["properties"]["configuration"]["ingress"]["external"] = True
    change["changeType"] = "Modify"
    change["delta"] = [{"path": "properties.template.containers"}]
    with pytest.raises(release.ReleaseError, match="full resource"):
        release.app_only_what_if(preview, baseline, desired)


@pytest.mark.parametrize("invalid", [
    "create", "delete", "unsupported", "unsupported-reason", "malformed-delta",
    "malformed-change", "contradictory-nochange", "unresolved-image",
])
def test_app_only_rejects_incomplete_or_contradictory_evidence(modules, invalid):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    preview = app_only_preview(apps, baseline)
    change = preview["changes"][0]
    if invalid in {"create", "delete", "unsupported"}:
        change["changeType"] = invalid.title()
    elif invalid == "unsupported-reason":
        change["unsupportedReason"] = "Cannot evaluate"
    elif invalid == "malformed-delta":
        change["delta"] = {}
    elif invalid == "malformed-change":
        preview["changes"][0] = None
    else:
        change["after"]["properties"]["template"]["containers"][0]["image"] = "[reference('app')]"
        if invalid == "unresolved-image":
            change["changeType"] = "Modify"
            change["delta"] = [{"path": "properties.template.containers"}]
    with pytest.raises(release.ReleaseError):
        release.app_only_what_if(preview, baseline, baseline)


def test_app_only_stable_readback_matches_template_api(modules):
    release, *_ = modules
    runner = Mock()
    subject = release.Release(
        release.parser().parse_args(["--app-only", "--update-existing"]), runner
    )
    subject.subscription, subject.group = "subscription", "group"
    subject.app("existing-api")
    command = runner.json.call_args.args[0]
    assert command[:4] == ["az", "rest", "--method", "get"]
    assert command[command.index("--url") + 1].endswith(
        f"/containerApps/existing-api?api-version={release.APP_API_VERSION}"
    )
    template = (LANE / "infra/app/update-existing.bicep").read_text()
    assert template.count(f"Microsoft.App/containerApps@{release.APP_API_VERSION}") == 2
    assert "Microsoft.DBforPostgreSQL" not in template
    assert "isSharedToAll" not in template


def test_app_only_snapshot_normalizes_only_absent_service_defaults(modules):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    raw = deepcopy(next(iter(apps.values())))
    props = raw["properties"]
    props["delegatedIdentities"] = []
    props["configuration"]["identitySettings"] = []
    props["configuration"]["registries"][0].update(username="", passwordSecretRef="")
    props["template"]["revisionSuffix"] = ""
    assert release.app_spec(raw) == next(iter(baseline.values()))
    props["configuration"]["registries"][0]["username"] = "retained"
    assert release.app_spec(raw)["properties"]["configuration"]["registries"][0]["username"]
    props["delegatedIdentities"] = [{"resourceId": "/some-identity"}]
    with pytest.raises(release.ReleaseError, match="delegated identities"):
        release.app_spec(raw)
    props["delegatedIdentities"] = []
    raw["extendedLocation"] = {"name": "unhandled"}
    with pytest.raises(release.ReleaseError, match="unsupported resource fields"):
        release.app_spec(raw)


@pytest.mark.parametrize("variant", [
    "literal", "key-vault", "masked", "empty", "missing", "duplicate", "duplicate-descriptor",
    "changed-binding", "extra-field", "custom-revision",
])
def test_app_only_reads_and_preserves_existing_secret_bindings(modules, capsys, variant):
    release, *_ = modules
    apps, _ = app_only_fixture(release)
    app = deepcopy(next(iter(apps.values())))
    props = app["properties"]
    props.update(
        provisioningState="Succeeded", runningStatus="Running",
        latestRevisionName="revision", latestReadyRevisionName="revision",
    )
    descriptor = {"name": "database-url"}
    actual = {"name": "database-url", "value": "private-old"}
    if variant == "key-vault":
        descriptor.update(
            keyVaultUrl="https://vault/secrets/database", identity="/existing-identity"
        )
        actual = {**descriptor, "value": None}
    props["configuration"]["secrets"] = [descriptor]
    secrets = [actual]
    if variant == "masked":
        actual["value"] = "**********"
    elif variant == "empty":
        actual["value"] = ""
    elif variant == "missing":
        secrets = []
    elif variant == "duplicate":
        secrets.append(dict(actual))
    elif variant == "duplicate-descriptor":
        props["configuration"]["secrets"].append(dict(descriptor))
    elif variant == "changed-binding":
        actual["keyVaultUrl"] = "https://different-vault/secrets/database"
    elif variant == "extra-field":
        actual["unknown"] = True
    elif variant == "custom-revision":
        props["template"]["revisionSuffix"] = "fixed"
    runner = Mock()
    runner.json.return_value = secrets
    subject = release.Release(
        release.parser().parse_args(["--app-only", "--update-existing"]), runner
    )
    subject.frontend_name = "maf-frontend"
    subject.group, subject.subscription = "group", "subscription"
    if variant in {"literal", "key-vault"}:
        result = subject.read_app_spec(app)
        expected = actual if variant == "literal" else descriptor
        assert result["properties"]["configuration"]["secrets"] == [expected]
        assert "--show-values" in runner.json.call_args.args[0]
    else:
        with pytest.raises(release.ReleaseError):
            subject.read_app_spec(app)
    assert "private-old" not in capsys.readouterr().out


def test_app_only_parameters_separate_secrets_from_nonsecret_objects(modules):
    release, *_ = modules
    apps, baseline = app_only_fixture(release)
    subject = release.Release(release.parser().parse_args(["--app-only", "--update-existing"]))
    subject.backend, subject.frontend = list(apps.values())
    parameters = subject.app_parameters(baseline)
    assert parameters["secretValues"] == {
        "backend": {"database-url": "private-old"}, "frontend": {},
    }
    assert "private-old" not in json.dumps(parameters["backend"])
    first = next(iter(baseline.values()))
    first["properties"]["template"]["containers"][0]["env"].append(
        {"name": "ACCIDENTAL_PLAINTEXT", "value": "private-old"}
    )
    with pytest.raises(release.ReleaseError, match="secret outside"):
        subject.app_parameters(baseline)


@pytest.mark.parametrize("invalid", [
    None, "digest", "registry", "repository", "tag", "write-lock", "delete-lock",
    "missing-output", "bad-status", "manifest-digest", "manifest-write-lock",
    "manifest-delete-lock", "tag-drift", "post-tag-write-lock", "post-tag-delete-lock",
])
@pytest.mark.parametrize("app_only", [False, True])
def test_build_checks_archive_image_provenance_and_both_lock_scopes(
    modules, tmp_path, invalid, app_only,
):
    release, *_ = modules
    runner = Mock()
    subject = release.Release(
        release.parser().parse_args(
            ["--app-only", "--update-existing"] if app_only else []
        ), runner
    )
    subject.workspace = tmp_path
    subject.subscription = "subscription"
    subject.registry_name, subject.registry_server = "registry", "registry.azurecr.io"
    commit = "a" * 40
    tag = commit + "-unique"
    digest = "sha256:" + "b" * 64
    responses = []
    for kind in ("backend", "frontend"):
        responses.extend([
            {"status": "Succeeded", "outputImages": [{
                "digest": digest, "registry": "registry.azurecr.io",
                "repository": f"model-harness-maf-{kind}", "tag": tag,
            }]},
            {"digest": digest, "changeableAttributes": {
                "writeEnabled": False, "deleteEnabled": False,
            }},
            {"digest": digest, "changeableAttributes": {
                "writeEnabled": False, "deleteEnabled": False,
            }},
            {"digest": digest, "changeableAttributes": {
                "writeEnabled": False, "deleteEnabled": False,
            }},
        ])
    if invalid in {"digest", "registry", "repository", "tag"}:
        responses[0]["outputImages"][0][invalid] = "mismatch"
    elif invalid == "write-lock":
        responses[1]["changeableAttributes"]["writeEnabled"] = True
    elif invalid == "delete-lock":
        responses[1]["changeableAttributes"]["deleteEnabled"] = True
    elif invalid == "missing-output":
        responses[0]["outputImages"] = None
    elif invalid == "bad-status":
        responses[0]["status"] = "Failed"
    elif invalid == "manifest-digest":
        responses[2]["digest"] = "sha256:" + "c" * 64
    elif invalid == "manifest-write-lock":
        responses[2]["changeableAttributes"]["writeEnabled"] = True
    elif invalid == "manifest-delete-lock":
        responses[2]["changeableAttributes"]["deleteEnabled"] = True
    elif invalid == "tag-drift":
        responses[3]["digest"] = "sha256:" + "c" * 64
    elif invalid == "post-tag-write-lock":
        responses[3]["changeableAttributes"]["writeEnabled"] = True
    elif invalid == "post-tag-delete-lock":
        responses[3]["changeableAttributes"]["deleteEnabled"] = True
    runner.json.side_effect = responses

    def run(command, **kwargs):
        if command[:2] == ["git", "archive"]:
            assert commit in command
            assert command[command.index("--") + 1:] == [
                "LICENSE", ".dockerignore", "shared", "agent-framework/double-charge/maf",
            ]
            path = next(
                arg.removeprefix("--output=") for arg in command if arg.startswith("--output=")
            )
            with release.tarfile.open(path, "w"):
                pass
        return ""

    runner.run.side_effect = run
    if invalid:
        with pytest.raises(release.ReleaseError):
            subject.build(commit, tag)
    else:
        assert subject.build(commit, tag) == {
            f"{kind}Image": f"registry.azurecr.io/model-harness-maf-{kind}@{digest}"
            for kind in ("backend", "frontend")
        }
        locks = [
            c.args[0] for c in runner.run.call_args_list
            if c.args[0][1:3] == ["acr", "repository"]
        ]
        assert len(locks) == 4
        assert all(c[c.index("--write-enabled") + 1] == "false" for c in locks)
        assert all(c[c.index("--delete-enabled") + 1] == "false" for c in locks)
        assert {c[c.index("--image") + 1] for c in locks} == {
            reference
            for kind in ("backend", "frontend")
            for reference in (
                f"model-harness-maf-{kind}:{tag}", f"model-harness-maf-{kind}@{digest}"
            )
        }
    assert not list(tmp_path.iterdir())


def configured_release(
    release,
    monkeypatch,
    *,
    apply=False,
    foundation=False,
    migration_error=False,
    update_existing=False,
):
    args = release.parser().parse_args(
        (["--apply", "--source-commit", "a" * 40] if apply else [])
        + (["--foundation"] if foundation else [])
        + (["--update-existing"] if update_existing else [])
    )
    operations = []
    runner = Mock()

    def run(command, **kwargs):
        if command[0].endswith("python") and any(part.endswith("migrate.py") for part in command):
            operations.append("migrate")
            assert kwargs["env"]["DATABASE_SCHEMA"] == release.SCHEMA
            assert "secret" not in " ".join(command)
            assert "--require-empty" in command
            if migration_error:
                raise release.ReleaseError("migration failed")
        elif "deploy" in command:
            operations.append("hosted-deploy")
        else:
            operations.append("setup")
        return ""

    runner.run.side_effect = run
    subject = release.Release(args, runner)
    subject.parameters = {
        "backendImage": "registry/old-api:old",
        "frontendImage": "registry/old-web:old",
        "backendTargetPort": 8010,
        "postgresSchema": release.SCHEMA if update_existing else "maf_double_charge",
        "postgresAdministratorPassword": "secret",
        "foundryProjectEndpoint": "https://project",
    }
    subject.schema = release.SCHEMA
    subject.registry_server = "registry"
    subject.group = "maf-only"
    subject.foundry_principal = "principal"
    subject.hosted_principal = "hosted-principal"
    subject.postgres_state = "Ready"
    subject.database_url = "postgresql://user:secret@host/database"
    subject.old_version = "3"
    subject.outputs = {"frontendUrl": "https://web"}
    subject.dirty = False
    monkeypatch.setattr(subject, "discover", lambda: None)
    monkeypatch.setattr(subject, "source_commit", lambda: "a" * 40)
    monkeypatch.setattr(
        subject, "verify_existing_schema", lambda: operations.append("schema-check")
    )

    def deploy(parameters, *, preview, suffix=""):
        if preview:
            operations.append("preview")
            assert parameters["postgresSchema"] == release.SCHEMA
            return {"changes": []}
        operations.append("foundation" if suffix else "rollout")
        assert parameters["postgresSchema"] == (
            "maf_double_charge" if suffix and not update_existing else release.SCHEMA
        )
        if suffix:
            assert parameters["backendImage"] == "registry/old-api:old"
            assert parameters["frontendImage"] == "registry/old-web:old"
        return {}

    monkeypatch.setattr(subject, "deploy_parameters", deploy)
    monkeypatch.setattr(subject, "build", lambda *args: operations.append("build"))
    monkeypatch.setattr(subject, "wait_apps", lambda parameters: operations.append("wait-apps"))
    monkeypatch.setattr(subject, "wait_hosted", lambda: "4")
    return subject, operations


def test_preview_never_builds_migrates_or_deploys(modules, monkeypatch, capsys):
    release, *_ = modules
    subject, operations = configured_release(release, monkeypatch)
    subject.execute()
    assert operations == ["preview"]
    assert "secret" not in capsys.readouterr().out


def test_existing_update_preview_only_checks_schema(modules, monkeypatch):
    release, *_ = modules
    subject, operations = configured_release(release, monkeypatch, update_existing=True)
    subject.execute()
    assert operations == ["preview", "schema-check"]


def test_existing_update_checks_before_foundation_and_never_migrates(modules, monkeypatch):
    release, *_ = modules
    subject, operations = configured_release(
        release, monkeypatch, apply=True, foundation=True, update_existing=True
    )
    subject.execute()
    assert operations == [
        "preview",
        "schema-check",
        "foundation",
        "wait-apps",
        "build",
        "rollout",
        "wait-apps",
        "setup",
        "setup",
        "setup",
        "hosted-deploy",
    ]


def test_existing_update_schema_failure_prevents_all_mutations(modules, monkeypatch):
    release, *_ = modules
    subject, operations = configured_release(
        release, monkeypatch, apply=True, foundation=True, update_existing=True
    )
    monkeypatch.setattr(
        subject, "verify_existing_schema", Mock(side_effect=release.ReleaseError("not current"))
    )
    with pytest.raises(release.ReleaseError, match="not current"):
        subject.execute()
    assert operations == ["preview"]


def test_preview_never_logs_full_resource_payloads(modules, monkeypatch, capsys):
    release, *_ = modules
    subject, operations = configured_release(release, monkeypatch)
    change = {
        "resourceId": "/subscriptions/sub/resourceGroups/rg/resource",
        "changeType": "Modify",
        "before": {"credentials": {"key": "private-before-value"}},
        "after": {"credentials": {"key": "private-after-value"}},
    }
    monkeypatch.setattr(subject, "deploy_parameters", lambda *args, **kwargs: {"changes": [change]})
    subject.execute()
    output = capsys.readouterr().out
    assert "private-before-value" not in output
    assert "private-after-value" not in output
    assert operations == []


def test_apply_orders_foundation_migration_rollout_and_hosted(modules, monkeypatch):
    release, *_ = modules
    subject, operations = configured_release(release, monkeypatch, apply=True, foundation=True)
    subject.execute()
    assert operations == [
        "preview",
        "foundation",
        "wait-apps",
        "migrate",
        "build",
        "rollout",
        "wait-apps",
        "setup",
        "setup",
        "setup",
        "hosted-deploy",
    ]


def test_migration_failure_never_rolls_out_new_runtime(modules, monkeypatch):
    release, *_ = modules
    subject, operations = configured_release(release, monkeypatch, apply=True, migration_error=True)
    with pytest.raises(release.ReleaseError):
        subject.execute()
    assert operations == ["preview", "migrate"]


@pytest.mark.parametrize(
    "change",
    [
        {
            "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.App/containerApps/new",
            "changeType": "Create",
        },
        {
            "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DBforPostgreSQL/flexibleServers/new",
            "changeType": "Create",
        },
        {
            "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/any/resource/old",
            "changeType": "Delete",
        },
    ],
)
def test_preview_rejects_replacement_topology_or_deletion(modules, monkeypatch, change):
    release, *_ = modules
    subject, operations = configured_release(release, monkeypatch, apply=True)
    monkeypatch.setattr(subject, "deploy_parameters", lambda *args, **kwargs: {"changes": [change]})
    with pytest.raises(release.ReleaseError):
        subject.execute()
    assert operations == []


@pytest.mark.parametrize("change_type", ["Deploy", "Unsupported", None, "Unknown"])
def test_preview_rejects_undetermined_changes_before_mutations(modules, monkeypatch, change_type):
    release, *_ = modules
    subject, operations = configured_release(release, monkeypatch, apply=True)
    change = {
        "resourceId": "/subscriptions/sub/resourceGroups/rg/resource",
        "changeType": change_type,
    }
    monkeypatch.setattr(subject, "deploy_parameters", lambda *args, **kwargs: {"changes": [change]})
    with pytest.raises(release.ReleaseError, match="could not determine"):
        subject.execute()
    assert operations == []


def test_raw_http_and_completed_sse_results(modules):
    _, hosted, *_ = modules
    result = {"run_id": "run-1", "status": "paused", "checkpoint_id": "checkpoint-1"}
    response = {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(result)}]}
        ],
    }
    assert (
        hosted.response_result(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + json.dumps(response)
        )
        == result
    )
    stream = 'data: {"type":"response.created"}\n\n'
    stream += "data: " + json.dumps({"type": "response.completed", "response": response}) + "\n\n"
    assert hosted.response_result(stream) == result


def test_raw_pending_and_error_responses_fail(modules):
    release, hosted, *_ = modules
    for body in (
        "HTTP/1.1 500 Error\r\n\r\n{}",
        '{"status":"in_progress","output":[]}',
        'data: {"type":"response.created"}\n\n',
        'data: {"type":"response.failed"}\n\n',
    ):
        with pytest.raises(release.ReleaseError):
            hosted.response_result(body)


def test_hosted_command_has_explicit_version_and_new_conversation(modules):
    _, hosted, *_ = modules
    runner = Mock()
    runner.run.return_value = json.dumps(
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"run_id":"run"}'}],
                }
            ],
        }
    )
    hosted.invoke(runner, "maf-dev", "4", {"action": "resume", "run_id": "run"})
    created, command, stopped = [call.args[0] for call in runner.run.call_args_list]
    session_id = created[created.index("--session-id") + 1]
    assert created[created.index("--version") + 1] == "4"
    assert session_id.startswith("maf-check-")
    assert "--version" not in command
    assert command[command.index("--session-id") + 1] == session_id
    assert "--new-conversation" in command and "--new-session" not in command
    assert "--output" in command and "raw" in command
    assert stopped[stopped.index("stop") + 1] == session_id


@pytest.mark.parametrize("failure_index", [0, 1, 2])
def test_hosted_session_cleanup_is_attempted_and_failures_are_explicit(
    modules, monkeypatch, failure_index
):
    release, hosted, *_ = modules
    runner = Mock()
    responses: list[str | Exception] = ["", "", ""]
    responses[failure_index] = release.ReleaseError("command failed")
    runner.run.side_effect = responses
    monkeypatch.setattr(hosted, "response_result", lambda _: {"run_id": "run"})
    with pytest.raises(release.ReleaseError):
        hosted.invoke(runner, "maf-dev", "5", {"action": "start"})
    commands = [call.args[0] for call in runner.run.call_args_list]
    session_id = commands[0][commands[0].index("--session-id") + 1]
    assert commands[-1][commands[-1].index("stop") + 1] == session_id


def test_invalid_hosted_response_still_stops_its_session(modules):
    release, hosted, *_ = modules
    runner = Mock()
    runner.run.return_value = "incomplete response"
    with pytest.raises(release.ReleaseError):
        hosted.invoke(runner, "maf-dev", "5", {"action": "start"})
    commands = [call.args[0] for call in runner.run.call_args_list]
    assert len(commands) == 3
    session_id = commands[0][commands[0].index("--session-id") + 1]
    assert commands[-1][commands[-1].index("stop") + 1] == session_id


def test_eval_binding_does_not_change_seed_intent(modules):
    _, _, binder, _ = modules
    original = {
        "agent": {"name": "model-harness-maf"},
        "dataset": {"local_uri": "seed.jsonl"},
        "evaluators": ["builtin.task_completion"],
    }
    bound = binder.bind(original, "4", SCRIPTS / "cases.jsonl")
    assert bound["agent"]["version"] == "4"
    assert "version" not in original["agent"]
    assert original["dataset"]["local_uri"] == "seed.jsonl"
    assert bound["evaluators"] == original["evaluators"]


@pytest.mark.parametrize(
    "path",
    [
        "infra/foundry-hosted/agent/.foundry/agent-metadata.yaml",
        "infra/foundry-hosted/agent/.foundry/results/maf-dev/example.json",
    ],
)
def test_hosted_generated_evaluation_artifacts_are_git_ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", path],
        cwd=LANE,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_hosted_evaluation_seed_is_not_git_ignored():
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "--quiet",
            "--",
            "infra/foundry-hosted/agent/.foundry/datasets/double-charge-hosted-cases.jsonl",
        ],
        cwd=LANE,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr.decode()


def test_api_scenario_harness_matches_real_test_factory(modules):
    from fastapi.testclient import TestClient
    from maf_double_charge.testing.app import create_test_app

    *_, e2e = modules
    with TestClient(create_test_app()) as client:
        for scenario in e2e.SCENARIOS:
            e2e.check_scenario(client, *scenario)


def load_hosted_adapter(monkeypatch):
    fake_sdk = ModuleType("azure.ai.agentserver.responses")
    host = Mock()
    host.run_async = AsyncMock(side_effect=RuntimeError("serve failed"))
    fake_sdk.ResponsesAgentServerHost = Mock(return_value=host)
    fake_sdk.TextResponse = Mock()
    monkeypatch.setitem(sys.modules, "azure.ai.agentserver.responses", fake_sdk)
    spec = importlib.util.spec_from_file_location(
        "maf_release_hosted_main", LANE / "infra/foundry-hosted/agent/main.py"
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    return adapter, host


@pytest.mark.asyncio
async def test_hosted_entrypoint_starts_and_always_closes_runtime(modules, monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false")
    adapter, host = load_hosted_adapter(monkeypatch)
    runtime = Mock(start=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(adapter, "create_runtime", Mock(return_value=runtime))
    with pytest.raises(RuntimeError, match="serve failed"):
        await adapter.main()
    adapter.create_runtime.assert_called_once_with(host="hosted")
    runtime.start.assert_awaited_once()
    runtime.close.assert_awaited_once()
    assert adapter._active_runtime is None


def test_hosted_content_capture_disabled_before_sdk_construction(monkeypatch):
    import yaml

    flag = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
    monkeypatch.setenv(flag, "true")
    adapter, host = load_hosted_adapter(monkeypatch)
    assert os.environ[flag] == "true", "Import must not change process configuration"

    def construct():
        assert os.environ[flag] == "false"
        return host

    monkeypatch.setattr(adapter, "ResponsesAgentServerHost", construct)
    assert adapter.create_host() is host
    host.response_handler.assert_called_once_with(adapter.response_handler)
    environment = yaml.safe_load((LANE / "azure.yaml").read_text())["services"][
        "model-harness-maf"
    ]["env"]
    assert environment[flag] == "false"
    assert "APPLICATIONINSIGHTS_CONNECTION_STRING" not in environment


def test_hosted_manifest_retains_complete_native_traces():
    import yaml

    environment = yaml.safe_load((LANE / "azure.yaml").read_text())["services"][
        "model-harness-maf"
    ]["env"]
    assert environment["OTEL_TRACES_SAMPLER"] == "microsoft.fixed_percentage"
    assert environment["OTEL_TRACES_SAMPLER_ARG"] == "1.0"


def test_hosted_manifest_disables_only_sdk_and_transport_instrumentation():
    import yaml

    environment = yaml.safe_load((LANE / "azure.yaml").read_text())["services"][
        "model-harness-maf"
    ]["env"]
    assert set(environment["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"].split(",")) == {
        "azure_sdk", "httpx", "httpx2", "requests", "urllib", "urllib3",
    }
    assert environment["AZURE_TRACING_ENABLED"] == "false"


def test_hosted_noise_policy_runs_after_sdk_setup_before_handler_registration(monkeypatch):
    adapter, host = load_hosted_adapter(monkeypatch)
    order = []

    def construct():
        order.append("sdk")
        return host

    monkeypatch.setattr(adapter, "ResponsesAgentServerHost", construct)
    monkeypatch.setattr(
        adapter, "apply_hosted_instrumentation_policy", lambda: order.append("policy")
    )
    host.response_handler.side_effect = lambda handler: order.append("handler")
    assert adapter.create_host() is host
    assert order == ["sdk", "policy", "handler"]


@pytest.mark.asyncio
async def test_hosted_adapter_executes_explicit_workflow_commands(
    modules, monkeypatch, repository, model, settings
):
    from maf_double_charge.bootstrap import create_runtime
    from maf_double_charge.testing.checkpoints import InMemoryRunCheckpointStorage

    *_, e2e = modules
    adapter, _ = load_hosted_adapter(monkeypatch)
    # API and hosted processes do not share the process-scoped telemetry provider in production.
    monkeypatch.setattr(
        "maf_double_charge.bootstrap.configure_telemetry", Mock(return_value=Mock())
    )
    runtime = create_runtime(
        settings,
        repository=repository,
        model=model,
        checkpoint_storage_factory=InMemoryRunCheckpointStorage,
        host="hosted",
    )
    monkeypatch.setattr(adapter, "_runtime", AsyncMock(return_value=runtime))
    await runtime.start()
    try:
        for index, (scenario, decision, terminal) in enumerate(e2e.SCENARIOS):
            identifier = f"hosted-offline-{index}"
            started = await adapter._execute(
                {
                    "action": "start",
                    "scenario_id": scenario,
                    "operator_id": identifier,
                    "customer_id": identifier,
                    "existing_case_id": identifier,
                    "idempotency_key": identifier,
                },
                identifier,
            )
            assert started["case_id"] == identifier
            assert len(started["events"]) <= 20
            investigation = started["investigation"]
            assert set(investigation) == {
                "duplicate_found", "duplicate_summary", "billing_validation", "policy_validation",
            }
            assert identifier not in json.dumps(investigation)
            result = started
            if decision:
                assert started["status"] == "paused" and started["approval_required"]
                assert investigation["duplicate_found"] is True
                assert investigation["duplicate_summary"]
                assert investigation["billing_validation"]["ok"] is True
                assert investigation["policy_validation"]["ok"] is True
                checkpoint = {
                    "operator_id": identifier,
                    "run_id": started["run_id"],
                    "checkpoint_id": started["checkpoint_id"],
                }
                recorded = await adapter._execute(
                    {
                        **checkpoint,
                        "action": "approval",
                        "decision": decision,
                        "reviewer_id": identifier,
                        "reason": "Reviewed fixture evidence.",
                    },
                    identifier,
                )
                assert recorded["status"] == "paused"
                assert recorded["refund_status"] == "not_requested"
                result = await adapter._execute({**checkpoint, "action": "resume"}, identifier)
            assert result["terminal_status"] == terminal
            if scenario == "retry-safe-refund":
                assert result["retry_count"] == 1
                assert result["outcome"]["refund_id"]
        seed = (
            LANE / "infra/foundry-hosted/agent/.foundry/datasets/double-charge-hosted-cases.jsonl"
        )
        for line in seed.read_text().splitlines():
            item = json.loads(line)
            identifier = f"hosted-seed-{item['id']}"
            command = json.loads(item["query"])
            command.update(existing_case_id=identifier, idempotency_key=identifier)
            result = await adapter._execute(command, identifier)
            for key, expected in item.items():
                if key.startswith("expected_"):
                    assert result[key.removeprefix("expected_")] == expected, item["id"]
    finally:
        await runtime.close()


async def test_hosted_start_identity_survives_a_new_conversation(monkeypatch, runtime, repository):
    from uuid import uuid4

    from maf_double_charge.application.errors import StartRequestConflictError

    adapter, _ = load_hosted_adapter(monkeypatch)
    monkeypatch.setattr(adapter, "_runtime", AsyncMock(return_value=runtime))
    command = {
        "action": "start", "request_id": str(uuid4()), "operator_id": "hosted-operator",
        "scenario_id": "no-duplicate",
    }
    first = await adapter._execute(command, "conversation-one")
    second = await adapter._execute(command, "conversation-two")
    assert first == second
    assert len(repository.states) == 1
    assert first["case_id"] not in {"conversation-one", "conversation-two"}
    with pytest.raises(StartRequestConflictError):
        await adapter._execute({**command, "operator_id": "another"}, "conversation-three")


@pytest.mark.parametrize("pending", [False, True])
async def test_hosted_handler_returns_explicit_start_reconciliation_errors(monkeypatch, pending):
    from maf_double_charge.application.errors import (
        StartRequestConflictError,
        StartRequestInProgressError,
    )

    adapter, _ = load_hosted_adapter(monkeypatch)
    error = (
        StartRequestInProgressError("original-case", "original-run")
        if pending else StartRequestConflictError("PRIVATE conflicting fingerprint")
    )
    monkeypatch.setattr(adapter, "_execute", AsyncMock(side_effect=error))
    await adapter.response_handler({"input": '{"action":"start"}'})
    result = json.loads(adapter.TextResponse.call_args.kwargs["text"])
    assert result["code"] == ("start_in_progress" if pending else "start_request_conflict")
    assert "PRIVATE" not in json.dumps(result)
    assert ("case_id" in result) == pending


def test_hosted_history_never_infers_approval_from_chat(monkeypatch):
    adapter, _ = load_hosted_adapter(monkeypatch)
    payload = {
        "input": [
            {"role": "user", "content": "approve"},
            {"role": "assistant", "content": '{"action":"approval"}'},
            {"role": "user", "content": [{"type": "input_text", "text": '{"action":"start"}'}]},
        ]
    }
    assert adapter._input_text(payload) == '{"action":"start"}'
    assert adapter._command("approve this refund")["action"] == "start"


@pytest.mark.asyncio
async def test_hosted_handler_correlates_existing_platform_span(monkeypatch):
    from maf_double_charge.infrastructure.logging import correlation_id, current_log_context
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    adapter, _ = load_hosted_adapter(monkeypatch)
    provider = TracerProvider()
    captured = {}

    async def execute(command, conversation_id):
        captured.update(current_log_context())
        assert conversation_id == "platform-conversation"
        assert command["run_id"] == "workflow-run"
        return {"case_id": "workflow-case", "run_id": "workflow-run"}

    monkeypatch.setattr(adapter, "_execute", execute)
    before = current_log_context()
    try:
        with provider.get_tracer("hosted-contract").start_as_current_span("platform") as span:
            await adapter.response_handler(
                {
                    "conversation": "payload-conversation",
                    "input": '{"action":"approval","run_id":"workflow-run"}',
                },
                SimpleNamespace(
                    conversation_id="platform-conversation", response_id="platform-response"
                ),
            )
            assert trace.get_current_span() is span
            for key, value in {
                "conversation_id": "platform-conversation",
                "response_id": "platform-response",
                "case_id": "workflow-case",
                "run_id": "workflow-run",
            }.items():
                assert span.attributes[key] == correlation_id(value)
            assert captured["response_id"] == correlation_id("platform-response")
            assert captured["conversation_id"] == correlation_id("platform-conversation")
            assert captured["run_id"] == correlation_id("workflow-run")
            assert current_log_context() == before
    finally:
        provider.shutdown()


@pytest.mark.asyncio
async def test_hosted_handler_omits_absent_platform_correlation_ids(monkeypatch):
    from maf_double_charge.infrastructure.logging import current_log_context
    from opentelemetry.sdk.trace import TracerProvider

    adapter, _ = load_hosted_adapter(monkeypatch)
    provider = TracerProvider()

    async def execute(command, case_fallback):
        assert command["action"] == "start"
        assert case_fallback.startswith("foundry-")
        assert "conversation_id" not in current_log_context()
        assert "response_id" not in current_log_context()
        return {"case_id": case_fallback, "run_id": "workflow-run"}

    monkeypatch.setattr(adapter, "_execute", execute)
    try:
        with provider.get_tracer("hosted-contract").start_as_current_span("platform") as span:
            await adapter.response_handler({"input": '{"action":"start"}'})
            assert "conversation_id" not in span.attributes
            assert "response_id" not in span.attributes
    finally:
        provider.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["approval", "resume"])
async def test_hosted_commands_correlate_authoritative_state_before_execution(monkeypatch, action):
    from maf_double_charge.application.models import WorkflowState
    from maf_double_charge.infrastructure.logging import correlation_id, current_log_context
    from maf_double_charge.infrastructure.telemetry import telemetry_context

    adapter, _ = load_hosted_adapter(monkeypatch)
    state = WorkflowState(
        case_id="authoritative-case",
        run_id="authoritative-run",
        complaint="Check duplicate charges",
        customer_id="customer",
        scenario_id="duplicate-confirmed",
        idempotency_key="unique-refund-key",
    )
    observed = {}

    async def execute(run_id, command, *, operator_id=None):
        assert run_id == state.run_id
        observed.update(current_log_context())
        return state

    service = SimpleNamespace(
        get_state=AsyncMock(return_value=state),
        get_outcome=AsyncMock(return_value=None),
        list_events=AsyncMock(return_value=[]),
        record_approval=AsyncMock(side_effect=execute),
        resume=AsyncMock(side_effect=execute),
    )
    runtime = SimpleNamespace(service=service)
    monkeypatch.setattr(adapter, "_runtime", AsyncMock(return_value=runtime))
    with telemetry_context(
        conversation_id="platform-conversation", response_id="platform-response"
    ):
        await adapter._execute(
            {
                "action": action,
                "operator_id": "hosted-operator",
                "run_id": "requested-run",
                "checkpoint_id": "checkpoint",
                "decision": "approve",
                "reviewer_id": "reviewer",
                "reason": "Reviewed fixture evidence.",
            },
            "platform-conversation",
        )
    assert service.get_state.call_args_list[0].args == ("requested-run",)
    service.list_events.assert_awaited_once_with(state.run_id)
    assert observed == {
        "case_id": correlation_id(state.case_id),
        "run_id": correlation_id(state.run_id),
        "conversation_id": correlation_id("platform-conversation"),
        "response_id": correlation_id("platform-response"),
    }


def test_release_scripts_have_no_shell_evaluation_or_bootstrap_placeholders():
    shell = (SCRIPTS / "deploy_azure.sh").read_text()
    assert "eval " not in shell
    source = (SCRIPTS / "release.py").read_text()
    assert "shell=True" not in source
    bicep = (LANE / "infra/app/main.bicep").read_text()
    assert "helloworld" not in bicep
    assert "external: false" in bicep


def test_app_and_hosted_framework_versions_match_the_frozen_lock():
    lock = tomllib.loads((LANE / "uv.lock").read_text())
    packages = {package["name"]: package for package in lock["package"]}
    requirements = (LANE / "infra/foundry-hosted/agent/requirements.txt").read_text().splitlines()
    for name, version in (
        ("agent-framework-core", "1.16.0"),
        ("agent-framework-foundry", "1.11.0"),
        ("agent-framework-openai", "1.14.1"),
        ("azure-ai-projects", "2.3.0"),
        ("openai", "2.54.0"),
    ):
        assert packages[name]["version"] == version
        assert f"{name}=={version}" in requirements
    assert "azure-ai-agentserver-core==2.0.0" in requirements
    assert "azure-ai-agentserver-responses==2.0.0" in requirements
    assert packages["model-to-harness-shared"]["source"]["editable"] == "../../../shared"
    dockerfile = (LANE / "infra/container/Dockerfile").read_text()
    assert "ghcr.io/astral-sh/uv:0.11.2" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "WORKDIR /workspace/agent-framework/double-charge/maf" in dockerfile
    assert "COPY shared/src /workspace/shared/src" in dockerfile
    assert "pip install" not in dockerfile


def test_hosted_telemetry_uses_the_compatible_platform_distro():
    requirements = (LANE / "infra/foundry-hosted/agent/requirements.txt").read_text().splitlines()
    assert "microsoft-opentelemetry==1.3.9" in requirements
    for name in (
        "opentelemetry-api",
        "opentelemetry-sdk",
        "opentelemetry-exporter-otlp-proto-http",
    ):
        assert f"{name}>=1.44,<1.45" in requirements
    assert not any(line.startswith("azure-monitor-opentelemetry==") for line in requirements)


def test_api_release_packages_use_the_approved_mirror_without_tls_bypass():
    from urllib.parse import urlsplit

    mirror = "https://packagefeedproxy.microsoft.io/pypi/simple/"
    manifest = tomllib.loads((LANE / "pyproject.toml").read_text())
    indexes = manifest["tool"]["uv"]["index"]
    assert [index["url"] for index in indexes if index.get("default")] == [mirror]
    lock = tomllib.loads((LANE / "uv.lock").read_text())
    for package in lock["package"]:
        if registry := package.get("source", {}).get("registry"):
            assert registry == mirror
        artifacts = [package["sdist"]] if "sdist" in package else []
        artifacts += package.get("wheels", [])
        for artifact in artifacts:
            assert urlsplit(artifact["url"]).hostname in {
                "packagefeedproxy.microsoft.io",
                "ms-feed-25.pkgs.visualstudio.com",
            }
    dockerfile = (LANE / "infra/container/Dockerfile").read_text()
    assert "--allow-insecure-host" not in dockerfile
    assert "UV_INDEX_URL" not in dockerfile
    assert "--index-url" not in dockerfile
