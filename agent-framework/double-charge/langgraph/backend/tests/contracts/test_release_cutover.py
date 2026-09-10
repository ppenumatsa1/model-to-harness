from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import stat
import zipfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

LANE = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("langgraph_release", LANE / "scripts/release.py")
assert spec and spec.loader
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def package_smoke(monkeypatch):
    monkeypatch.syspath_prepend(str(LANE / "scripts"))
    specification = importlib.util.spec_from_file_location(
        "langgraph_package_smoke", LANE / "scripts/package_smoke.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_hosted_gate_builds_pinned_runtime_instead_of_reusing_caller(
    package_smoke, monkeypatch, capsys
):
    calls = []
    caller = "/fixture/local-python3.12"
    monkeypatch.setattr(package_smoke.sys, "executable", caller)
    monkeypatch.setattr(package_smoke.sys, "argv", ["package_smoke.py", "--hosted"])
    monkeypatch.setenv("DATABASE_URL", "private-database")
    monkeypatch.setenv("VIRTUAL_ENV", "/fixture/local-venv")
    monkeypatch.setattr(package_smoke, "prepare", lambda path: path.mkdir())

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return release.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(package_smoke.subprocess, "run", run)
    package_smoke.main()
    assert calls[0][0][:5] == ["uv", "venv", "--python", "3.13", "--quiet"]
    assert calls[1][0][:3] == ["uv", "pip", "sync"]
    assert "--require-hashes" in calls[1][0]
    assert calls[1][0][-1].endswith("/agent/requirements.txt")
    assert calls[2][0][:3] == ["uv", "pip", "check"]
    executable = calls[3][0][0]
    assert executable != caller and executable.endswith("/hosted-venv/bin/python")
    assert calls[1][0][4] == executable and calls[2][0][-1] == executable
    assert all("DATABASE_URL" not in options["env"] for _, options in calls)
    assert all("VIRTUAL_ENV" not in options["env"] for _, options in calls)
    assert not Path(executable).parent.parent.parent.exists()
    assert "passed offline" in capsys.readouterr().out


def test_hosted_hash_install_failure_stops_before_smoke(package_smoke, monkeypatch, tmp_path):
    commands = []

    def run(command, **kwargs):
        assert kwargs["check"] is True
        commands.append(command)
        if command[:3] == ["uv", "pip", "sync"]:
            raise release.subprocess.CalledProcessError(1, command)
        return release.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(package_smoke.subprocess, "run", run)
    with pytest.raises(release.subprocess.CalledProcessError):
        package_smoke.hosted_python(tmp_path, tmp_path / "agent", {})
    assert len(commands) == 2


def test_runner_error_identifies_operation_and_safe_nested_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release, "LANE", tmp_path)
    secret = "postgresql://user:private-password@database"
    document = {
        "error": {
            "code": "DeploymentFailed",
            "message": secret,
            "details": [{"code": "ResourceNotFound", "message": secret}],
            "innererror": {"code": "unknown-private-value", "message": secret},
        }
    }
    command = ["az", "deployment", "group", "what-if", "--parameters", secret]
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: release.subprocess.CompletedProcess(
            command, 1, "", "ERROR: " + json.dumps(document)
        ),
    )
    with pytest.raises(release.ReleaseError) as failed:
        release.Runner().run(command)
    message = str(failed.value)
    assert "az deployment group what-if" in message
    assert "DeploymentFailed" in message and "ResourceNotFound" in message
    output = capsys.readouterr().out
    assert secret not in message + output
    assert "unknown-private-value" not in message + output
    artifact = Path(json.loads(output)["arm_preview_artifact"])
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
    assert json.loads(artifact.read_text())["stderr"] == "ERROR: " + json.dumps(document)


def test_runner_invalid_arm_json_preserves_private_evidence(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release, "LANE", tmp_path)
    command = ["az", "deployment", "group", "what-if"]
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: release.subprocess.CompletedProcess(
            command, 0, "private-unparseable-output", ""
        ),
    )
    with pytest.raises(release.ReleaseError, match="az deployment group what-if"):
        release.Runner().json(command)
    output = capsys.readouterr().out
    assert "private-unparseable-output" not in output
    artifact = Path(json.loads(output)["arm_preview_artifact"])
    assert json.loads(artifact.read_text())["stdout"] == "private-unparseable-output"


def test_command_operation_never_echoes_arguments():
    assert (
        release.command_operation(
            ["azd", "ai", "agent", "invoke", "private complaint", "--environment", "langgraph"]
        )
        == "azd ai agent invoke"
    )
    assert release.command_operation(["az", "unknown-secret-argument"]) == "az"
    assert release.safe_cli_error_codes(
        "ERROR: (AuthorizationFailed) private-message",
        "ERROR: unrecognized arguments: private-argument",
    ) == ["AuthorizationFailed", "UnrecognizedArguments"]


def test_runner_reports_actual_stopped_server_what_if_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release, "LANE", tmp_path)
    command = ["az", "deployment", "group", "what-if", "--parameters", "private-parameters"]
    error = (
        "ERROR: DeploymentWhatIfResourceError - Resource error for private-scope.\n"
        "ServerStoppedError - Server 'private-server' is in 'Stopped' state."
    )
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: release.subprocess.CompletedProcess(command, 1, "", error),
    )
    with pytest.raises(release.ReleaseError) as failed:
        release.Runner().run(command)
    message = str(failed.value)
    assert "az deployment group what-if" in message
    assert "DeploymentWhatIfResourceError, ServerStoppedError" in message
    assert "explicitly start existing PostgreSQL after review" in message
    assert "private-" not in message + capsys.readouterr().out


def test_lane_local_azd_helpers_are_explicit_and_read_only():
    commands = []

    class Runner:
        def json(self, command):
            commands.append(command)
            return {"AZURE_ENV_NAME": "langgraph", "DATABASE_URL": "fixture"}

    assert release.environment_values(Runner(), "langgraph")["AZURE_ENV_NAME"] == "langgraph"
    assert commands == [
        [
            "azd",
            "env",
            "get-values",
            "--output",
            "json",
            "--environment",
            "langgraph",
        ]
    ]
    with pytest.raises(release.ReleaseError):
        release.azd_args("", "ai", "agent", "show")


@pytest.mark.parametrize("payload", [None, [], {"DATABASE_URL": None}, {"count": 13}])
def test_environment_helper_rejects_nonstring_configuration(payload):
    class Runner:
        def json(self, command):
            return payload

    with pytest.raises(release.ReleaseError):
        release.environment_values(Runner(), "langgraph")


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "active", "version": "13"},
        {"status": "deployed", "agent_version": 13},
        {"status": "ACTIVE", "version": 13, "agent_version": "13"},
    ],
)
def test_active_agent_returns_authoritative_version(payload):
    assert release.active_agent(payload) == "13"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "failed", "version": "13"},
        {"status": "active"},
        {"status": "active", "version": True},
        {"status": "active", "version": "13", "agent_version": "12"},
    ],
)
def test_active_agent_rejects_inactive_missing_and_conflicting_versions(payload):
    with pytest.raises(release.ReleaseError):
        release.active_agent(payload)


def test_stopped_postgres_allows_preview_but_never_implicit_start():
    assert release.postgres_preflight("Stopped", apply=False) == "stopped"
    assert release.postgres_preflight("Ready", apply=True) == "ready"
    with pytest.raises(release.ReleaseError, match="explicitly start"):
        release.postgres_preflight("Stopped", apply=True)
    with pytest.raises(release.ReleaseError, match="unexpected state"):
        release.postgres_preflight("Updating", apply=False)


@pytest.mark.parametrize(
    "configured,explicit,expected",
    [
        (None, None, "langgraph"),
        ("", None, "langgraph"),
        ("selected-langgraph", None, "selected-langgraph"),
        ("selected-langgraph", "explicit-langgraph", "explicit-langgraph"),
    ],
)
def test_release_environment_uses_actual_lane_default(monkeypatch, configured, explicit, expected):
    if configured is None:
        monkeypatch.delenv("AZURE_ENV_NAME", raising=False)
    else:
        monkeypatch.setenv("AZURE_ENV_NAME", configured)
    arguments = ["release.py"]
    if explicit:
        arguments.extend(["--environment", explicit])
    monkeypatch.setattr(release.sys, "argv", arguments)
    observed = []
    monkeypatch.setattr(
        release.Release, "execute", lambda self: observed.append(self.args.environment)
    )
    release.main()
    assert observed == [expected]


@pytest.mark.parametrize(
    "selected,current,update",
    [
        (("langgraph_app_cutover", "langgraph_app_cutover"), ("old_a", "old_b"), False),
        (("maf_app", "langgraph_checkpoints_cutover"), ("old_a", "old_b"), False),
        (("langgraph_app", "langgraph_checkpoints"), ("old_a", "old_b"), False),
        (("langgraph_bad;drop", "langgraph_checkpoints_cutover"), ("old_a", "old_b"), False),
        (release.SCHEMAS, ("langgraph_app_cutover", "old_b"), False),
        (release.SCHEMAS, ("old_a", "old_b"), True),
    ],
)
def test_schema_pair_rejects_unsafe_or_wrong_mode(selected, current, update):
    with pytest.raises(release.ReleaseError):
        release.validate_schemas(selected, current, update)


def test_schema_pair_supports_fresh_and_verify_existing():
    release.validate_schemas(release.SCHEMAS, ("langgraph_app", "langgraph_checkpoints"), False)
    release.validate_schemas(release.SCHEMAS, release.SCHEMAS, True)


@pytest.mark.parametrize(
    "reference",
    [
        "registry.azurecr.io/model-harness-langgraph-backend:latest",
        "registry.azurecr.io/model-harness-maf-backend@" + "sha256:" + "a" * 64,
        "elsewhere.azurecr.io/model-harness-langgraph-backend@" + "sha256:" + "a" * 64,
    ],
)
def test_image_requires_lane_registry_and_digest(reference):
    with pytest.raises(release.ReleaseError):
        release.immutable_image(reference, "registry.azurecr.io", "model-harness-langgraph-backend")


def test_private_parameter_file_permissions_and_cleanup():
    with release.private_parameters({"password": "test-only"}) as path:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert json.loads(path.read_text())["parameters"]["password"]["value"] == "test-only"
    assert not path.exists()


def test_build_staging_excludes_credentials_caches_evaluations_and_other_lane(
    tmp_path, monkeypatch
):
    root = tmp_path / "repository"
    lane = root / "agent-framework/double-charge/langgraph"
    monkeypatch.setattr(release, "ROOT", root)
    monkeypatch.setattr(release, "LANE", lane)
    names = [
        "LICENSE",
        "shared/src/model_to_harness_shared/domain/models.py",
        "shared/.env",
        "agent-framework/double-charge/langgraph/backend/src/model_to_harness_langgraph/bootstrap.py",
        "agent-framework/double-charge/langgraph/backend/migrations/001_app.sql",
        "agent-framework/double-charge/langgraph/frontend/src/main.tsx",
        "agent-framework/double-charge/langgraph/frontend/.npmrc",
        "agent-framework/double-charge/langgraph/.azure/test/.env",
        "agent-framework/double-charge/langgraph/evals/results.json",
        "agent-framework/double-charge/langgraph/infra/foundry-hosted/agent/.foundry/results.json",
        "agent-framework/double-charge/langgraph/backend/src/model_to_harness_langgraph/__pycache__/x.pyc",
        "agent-framework/double-charge/maf/backend/src/private.py",
    ]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")

    class Tracked:
        def run(self, *args, **kwargs):
            return "\0".join(names) + "\0"

    stage = tmp_path / "stage"
    manifest = release.stage_sources(stage, Tracked())
    assert set(manifest) == {names[index] for index in (0, 1, 3, 4, 5)}
    assert {
        path.relative_to(stage).as_posix() for path in stage.rglob("*") if path.is_file()
    } == set(manifest)


def archive_fixture(tmp_path, extra=None):
    (tmp_path / "main.py").write_text("pass\n")
    digest = hashlib.sha256((tmp_path / "main.py").read_bytes()).hexdigest()
    (tmp_path / "SOURCE_MANIFEST.json").write_text(json.dumps({"main.py": digest}))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in ("main.py", "SOURCE_MANIFEST.json"):
            archive.write(tmp_path / name, name)
        if extra:
            archive.writestr(extra, "private")
    content = buffer.getvalue()
    return content, hashlib.sha256(content).hexdigest()


def test_archive_matches_source_and_authoritative_hash(tmp_path):
    content, digest = archive_fixture(tmp_path)
    assert release.verify_code_archive(tmp_path, content, digest) == digest
    with pytest.raises(release.ReleaseError):
        release.verify_code_archive(tmp_path, content, "0" * 64)
    (tmp_path / "main.py").write_text("changed")
    with pytest.raises(release.ReleaseError):
        release.verify_code_archive(tmp_path, content, digest)


@pytest.mark.parametrize("extra", [".env", ".foundry/results.json", "../escape", "main.py"])
def test_archive_rejects_secret_cache_traversal_and_duplicate(tmp_path, extra):
    content, digest = archive_fixture(tmp_path, extra)
    with pytest.raises(release.ReleaseError):
        release.verify_code_archive(tmp_path, content, digest)


def test_hosted_environment_prohibits_reserved_override_and_drift():
    release.verify_hosted_environment({"LANGGRAPH_SCHEMA": "ok"}, {"LANGGRAPH_SCHEMA": "ok"})
    for actual in (
        {"LANGGRAPH_SCHEMA": "wrong"},
        {"LANGGRAPH_SCHEMA": "ok", "APPLICATIONINSIGHTS_CONNECTION_STRING": "test-only"},
    ):
        with pytest.raises(release.ReleaseError):
            release.verify_hosted_environment(actual, {"LANGGRAPH_SCHEMA": "ok"})


def what_if(kind="NoChange", **kwargs):
    return {
        "status": "Succeeded",
        "changes": [
            {"resourceId": "/api", "changeType": kind, **kwargs},
            {"resourceId": "/web", "changeType": "NoChange"},
        ],
    }


@pytest.mark.parametrize("kind", ["Create", "Delete", "Deploy", "Unsupported", "Modify", "Ignore"])
def test_baseline_what_if_fails_closed(kind):
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(what_if(kind), {"/api", "/web"})


def test_what_if_requires_both_apps_and_success():
    for result in (
        {"status": "Failed", "changes": []},
        {"status": "Succeeded", "changes": []},
        {
            "status": "Succeeded",
            "changes": [
                {"resourceId": "/api", "changeType": "NoChange"},
            ],
        },
    ):
        with pytest.raises(release.ReleaseError):
            release.validate_what_if(result, {"/api", "/web"})
    release.validate_what_if(what_if(), {"/api", "/web"})


def test_rollout_requires_exact_environment_and_narrow_delta():
    payload = {"properties": {"template": {"containers": [{"image": "digest", "env": []}]}}}
    result = what_if(
        "Modify",
        before=payload,
        after=payload,
        delta=[{"path": "properties.template.containers[0].image"}],
    )
    expected = {"/api": {"image": "digest", "env": []}}
    release.validate_what_if(result, {"/api", "/web"}, rollout=True, expected=expected)
    expected["/api"]["env"] = [{"name": "UNREVIEWED", "value": "bad"}]
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"}, rollout=True, expected=expected)
    expected["/api"]["env"] = []
    result["changes"][0]["delta"] = [{"path": "properties.configuration.ingress.external"}]
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"}, rollout=True, expected=expected)


def test_identical_unmanaged_ignore_is_not_an_arm_mutation():
    result = what_if()
    result["changes"].append(
        {
            "resourceId": "/maf",
            "changeType": "Ignore",
            "before": {"name": "untouched", "properties": {"setting": "unchanged"}},
            "after": {"name": "untouched", "properties": {"setting": "unchanged"}},
            "delta": [],
        }
    )
    release.validate_what_if(result, {"/api", "/web"})


@pytest.mark.parametrize(
    "override",
    [
        {"resourceId": "/api"},
        {"before": None, "after": None},
        {"after": {"name": "changed"}},
        {"delta": [{"path": "properties.setting", "propertyChangeType": "Modify"}]},
        {"diagnostics": [{"code": "ExpansionLimit"}]},
        {"unsupportedReason": "ShortCircuited"},
        {"changeType": "Modify"},
        {"changeType": "Create"},
        {"changeType": "Delete"},
        {"changeType": "Deploy"},
    ],
)
def test_ignore_never_hides_unevaluated_apps_or_other_lane_mutations(override):
    result = what_if()
    result["changes"].append(
        {
            "resourceId": "/maf",
            "changeType": "Ignore",
            "before": {"name": "untouched"},
            "after": {"name": "untouched"},
            **override,
        }
    )
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"})


def test_arm_global_diagnostics_and_contradictory_nochange_fail():
    result = what_if()
    result["diagnostics"] = [{"code": "ExpansionLimit"}]
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"})
    result = what_if()
    result["changes"][0]["delta"] = [{"path": "identity", "propertyChangeType": "Modify"}]
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"})


def service_default_preview():
    before = {
        "properties": {
            "runningStatus": "Running",
            "configuration": {"ingress": {"exposedPort": 0}},
            "template": {"containers": [{"image": "unchanged", "env": []}]},
        }
    }
    after = deepcopy(before)
    del after["properties"]["runningStatus"]
    del after["properties"]["configuration"]["ingress"]["exposedPort"]
    return what_if(
        "Modify",
        before=before,
        after=after,
        delta=[
            {"path": "properties.runningStatus", "propertyChangeType": "Delete"},
            {
                "path": "properties.configuration.ingress.exposedPort",
                "propertyChangeType": "Delete",
            },
        ],
    )


def test_baseline_accepts_only_observed_readonly_and_zero_port_omissions():
    release.validate_what_if(service_default_preview(), {"/api", "/web"})
    for value in (80, None, "0"):
        result = service_default_preview()
        result["changes"][0]["before"]["properties"]["configuration"]["ingress"]["exposedPort"] = (
            value
        )
        with pytest.raises(release.ReleaseError):
            release.validate_what_if(result, {"/api", "/web"})
    result = service_default_preview()
    result["changes"][0]["before"]["properties"]["runningStatus"] = "Stopped"
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"})
    result = service_default_preview()
    result["changes"][0]["delta"][0]["propertyChangeType"] = "Modify"
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"})


@pytest.mark.parametrize(
    "path",
    [
        "properties.configuration.ingress.traffic",
        "properties.configuration.registries[0].server",
        "properties.configuration.secrets",
        "properties.template.containers[0].env[0].value",
        "identity.userAssignedIdentities",
    ],
)
def test_baseline_rejects_meaningful_changes_alongside_service_noise(path):
    result = service_default_preview()
    result["changes"][0]["delta"].append({"path": path, "propertyChangeType": "Modify"})
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"})


def nested_container_delta(path):
    return [
        {
            "path": "properties.template.containers",
            "propertyChangeType": "Array",
            "children": [
                {
                    "path": "0",
                    "propertyChangeType": "Modify",
                    "children": [{"path": path, "propertyChangeType": "Modify"}],
                }
            ],
        }
    ]


def test_nested_arm_array_deltas_preserve_exact_runtime_paths():
    deltas = nested_container_delta("env[3].value")
    assert [path for path, _ in release.delta_leaves(deltas)] == [
        "properties.template.containers[0].env[3].value"
    ]
    payload = {
        "properties": {
            "template": {
                "containers": [
                    {"image": "digest", "env": [{"name": "LANGGRAPH_SCHEMA", "value": "cutover"}]}
                ]
            }
        }
    }
    wanted = {"/api": deepcopy(payload["properties"]["template"]["containers"][0])}
    result = what_if("Modify", before=payload, after=payload, delta=deltas)
    release.validate_what_if(result, {"/api", "/web"}, rollout=True, expected=wanted)
    result["changes"][0]["delta"] = nested_container_delta("resources.cpu")
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"}, rollout=True, expected=wanted)
    result["changes"][0]["delta"] = deltas
    wanted["/api"]["env"][0]["value"] = "unapproved"
    with pytest.raises(release.ReleaseError):
        release.validate_what_if(result, {"/api", "/web"}, rollout=True, expected=wanted)


@pytest.mark.parametrize("deltas", [[None], [{}], [{"path": "x", "children": {}}]])
def test_malformed_nested_arm_deltas_fail_closed(deltas):
    with pytest.raises(release.ReleaseError):
        list(release.delta_leaves(deltas))


def reference_apps():
    apps = {}
    for kind in ("backend", "frontend"):
        identity = f"/subscriptions/fixture/resourceGroups/langgraph/identities/{kind}"
        apps[kind] = {
            "identity": {"userAssignedIdentities": {identity: {"clientId": kind + "-client"}}},
            "properties": {
                "configuration": {
                    "activeRevisionsMode": "Single",
                    "ingress": {
                        "fqdn": kind + ".example.test",
                        "traffic": [{"latestRevision": True, "weight": 100}],
                    },
                    "registries": [
                        {"server": "registry.example.test", "identity": identity.lower()}
                    ],
                },
                "template": {
                    "containers": [
                        {
                            "env": [
                                {"name": "AZURE_CLIENT_ID", "value": kind + "-client"},
                                {"name": "BACKEND_HOST", "value": "backend.example.test"},
                            ]
                        }
                    ]
                },
            },
        }
    return apps


def test_resolved_app_parameters_verify_existing_reference_linkage_case_insensitively():
    assert release.app_reference_parameters(reference_apps(), "registry.example.test") == {
        "registryEndpoint": "registry.example.test",
        "backendClientId": "backend-client",
        "backendHost": "backend.example.test",
    }


@pytest.mark.parametrize("field", ["traffic", "registry", "identity", "client", "host", "topology"])
def test_resolved_app_parameters_reject_unreviewed_reference_drift(field):
    apps = reference_apps()
    configuration = apps["backend"]["properties"]["configuration"]
    if field == "traffic":
        configuration["ingress"]["traffic"] = [{"revisionName": "old", "weight": 100}]
    elif field == "registry":
        configuration["registries"][0]["server"] = "other.example.test"
    elif field == "identity":
        configuration["registries"][0]["identity"] = "/other"
    elif field == "client":
        apps["backend"]["properties"]["template"]["containers"][0]["env"][0]["value"] = "other"
    elif field == "host":
        apps["frontend"]["properties"]["template"]["containers"][0]["env"][1]["value"] = "other"
    else:
        apps["backend"]["properties"]["template"]["containers"].append({"env": []})
    with pytest.raises(release.ReleaseError):
        release.app_reference_parameters(apps, "registry.example.test")


class RecordingRelease(release.Release):
    def __init__(self, *, apply=True, update=False, fail_final=False):
        super().__init__(
            argparse.Namespace(
                apply=apply,
                update_existing=update,
                schemas=release.SCHEMAS,
            )
        )
        self.calls = []
        self.fail_final = fail_final

    def discover(self):
        self.calls.append("discover")
        self.postgres_state = "ready"
        self.app_ids = {"/api", "/web"}
        self.parameters = {}
        self.apps = {
            kind: {
                "id": name,
                "properties": {
                    "template": {
                        "containers": [
                            {"env": []},
                        ]
                    }
                },
            }
            for kind, name in (("backend", "/api"), ("frontend", "/web"))
        }

    def source(self):
        self.calls.append("source")
        return "a" * 40

    def arm(self, parameters, *, preview):
        self.calls.append("what-if" if preview else "rollout")
        if self.fail_final and "backendImage" in parameters:
            return what_if("Delete")
        return what_if()

    def build(self, commit):
        self.calls.append("build")
        return {"backendImage": "digest", "frontendImage": "digest"}

    def setup(self):
        self.calls.append("verify-schema" if self.args.update_existing else "migrate")

    def verify_rollout(self, desired):
        self.calls.append("verify-rollout")


def test_fresh_release_orders_migration_before_rollout():
    candidate = RecordingRelease()
    candidate.execute()
    assert candidate.calls == [
        "discover",
        "source",
        "what-if",
        "build",
        "what-if",
        "source",
        "migrate",
        "rollout",
        "verify-rollout",
    ]


def test_update_existing_is_verify_only_before_build():
    candidate = RecordingRelease(update=True)
    candidate.execute()
    assert candidate.calls == [
        "discover",
        "source",
        "what-if",
        "verify-schema",
        "build",
        "what-if",
        "source",
        "rollout",
        "verify-rollout",
    ]


def test_preview_never_builds_migrates_or_rolls_out():
    candidate = RecordingRelease(apply=False)
    candidate.execute()
    assert candidate.calls == ["discover", "source", "what-if"]


def test_stopped_preview_reports_actionable_without_claiming_schema_readiness(capsys):
    class StoppedRelease(RecordingRelease):
        def discover(self):
            super().discover()
            self.postgres_state = "stopped"

    candidate = StoppedRelease(apply=False)
    candidate.execute()
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["postgres_state"] == "stopped"
    assert "explicitly start" in evidence["required_before_apply"]
    candidate = StoppedRelease(apply=False, update=True)
    with pytest.raises(release.ReleaseError, match="existing-schema verification is blocked"):
        candidate.execute()
    assert "verify-schema" not in candidate.calls


def test_rejected_final_what_if_cannot_migrate_or_roll_out():
    candidate = RecordingRelease(fail_final=True)
    with pytest.raises(release.ReleaseError):
        candidate.execute()
    assert "migrate" not in candidate.calls and "rollout" not in candidate.calls


def test_full_previews_persist_privately_before_rejected_rollout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release, "LANE", tmp_path)
    secret = "private-connection-string-sentinel"
    rejected = what_if("Delete", before={"secret": secret})
    rejected["error"] = {"message": secret}
    results = iter([what_if(), rejected])

    class Runner:
        def json(self, command):
            assert "what-if" in command and "create" not in command
            assert "FullResourcePayloads" in command
            return next(results)

    class PersistedRelease(RecordingRelease):
        def discover(self):
            super().discover()
            self.subscription = "fixture-subscription"
            self.group = "fixture-group"
            self.args.deployment = release.SERVICE
            self.runner = Runner()

        def arm(self, parameters, *, preview):
            return release.Release.arm(self, parameters, preview=preview)

    candidate = PersistedRelease()
    with pytest.raises(release.ReleaseError):
        candidate.execute()
    artifacts = sorted((tmp_path / ".azure/release").glob("arm-what-if-*.json"))
    assert len(artifacts) == 2
    assert {path.name for path in artifacts} == {
        json.loads(line)["arm_preview_artifact"].split("/")[-1]
        for line in capsys.readouterr().out.splitlines()
    }
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in artifacts)
    assert stat.S_IMODE(artifacts[0].parent.stat().st_mode) == 0o700
    assert rejected in [json.loads(path.read_text()) for path in artifacts]
    assert "migrate" not in candidate.calls and "rollout" not in candidate.calls


def test_preview_stdout_contains_only_safe_resource_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release, "LANE", tmp_path)
    resource = (
        "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-model-harness/"
        "providers/Microsoft.App/containerApps/langgraph-api"
    )
    secret = "postgresql://private:password@server/database"
    result = {
        "status": "Failed",
        "error": {"message": secret},
        "changes": [
            {"resourceId": resource, "changeType": "Modify", "after": {"password": secret}},
            {"resourceId": secret, "changeType": secret, "before": {"secret": secret}},
        ],
    }
    artifact = release.persist_arm_preview(result)
    output = capsys.readouterr().out
    assert secret not in output
    assert json.loads(artifact.read_text()) == result
    summary = json.loads(output)
    assert summary["arm_preview_artifact"] == str(artifact)
    assert summary["succeeded"] is False
    assert summary["resource_changes"] == [
        {"resource_id": resource, "change_type": "Modify"},
        {"resource_id": "[unavailable]", "change_type": "Unknown"},
    ]
    with pytest.raises(release.ReleaseError) as rejected:
        release.validate_what_if(what_if(secret), {"/api", "/web"})
    assert secret not in str(rejected.value)


def test_preview_artifacts_reject_symlink_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "LANE", tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ".azure").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(release.ReleaseError, match="symbolic link"):
        release.persist_arm_preview(what_if())
    assert not list(elsewhere.iterdir())


@pytest.mark.parametrize(
    "dirty,apply,allowed",
    [
        ("", True, True),
        (" M backend/source.py", True, False),
        ("?? backend/new.py", True, False),
        (" M backend/source.py", False, True),
    ],
)
def test_source_requires_committed_lane_before_apply(dirty, apply, allowed):
    calls = []

    class Runner:
        def run(self, command, **kwargs):
            calls.append(command)
            return "a" * 40 if command[:2] == ["git", "rev-parse"] else dirty

    candidate = release.Release(argparse.Namespace(apply=apply), Runner())
    if allowed:
        assert candidate.source() == "a" * 40
    else:
        with pytest.raises(release.ReleaseError, match="clean, validated"):
            candidate.source()
    assert "--untracked-files=all" in calls[1]
    assert "shared" in calls[1]
    assert release.LANE.relative_to(release.ROOT).as_posix() in calls[1]


def test_source_drift_during_staging_blocks_image_build(monkeypatch):
    candidate = release.Release(argparse.Namespace(apply=True))
    monkeypatch.setattr(release, "stage_sources", lambda *args: {"source.py": "digest"})
    monkeypatch.setattr(candidate, "source", lambda: "b" * 40)
    with pytest.raises(release.ReleaseError, match="Source changed during build staging"):
        candidate.build("a" * 40)


@pytest.mark.parametrize(
    "existing,locked,allowed",
    [
        ([], True, True),
        ([("langgraph_app_cutover",)], True, False),
        ([("langgraph_checkpoints_cutover",)], True, False),
        ([], False, False),
    ],
)
def test_fresh_setup_checks_both_namespaces_under_read_only_session_locks(
    monkeypatch, existing, locked, allowed
):
    from psycopg import AsyncConnection

    commands = []
    queries = []
    closed = []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(True)

        async def execute(self, query, parameters):
            queries.append((query, parameters))
            return self

        async def fetchone(self):
            return (locked,)

        async def fetchall(self):
            return existing

    async def connect(*args, **kwargs):
        assert kwargs["options"] == "-c default_transaction_read_only=on"
        assert kwargs["autocommit"] is True
        return Connection()

    class Runner:
        def run(self, command, **kwargs):
            assert not closed
            commands.append(command)

    monkeypatch.setattr(AsyncConnection, "connect", connect)
    candidate = release.Release(
        argparse.Namespace(update_existing=False, schemas=release.SCHEMAS), Runner()
    )
    candidate.database_url = "postgresql://fixture"
    if allowed:
        candidate.setup()
        assert commands == [[release.sys.executable, "scripts/setup_db.py", "--require-fresh"]]
        assert queries[-1][1] == (list(release.SCHEMAS),)
    else:
        with pytest.raises(release.ReleaseError):
            candidate.setup()
        assert not commands
    assert closed == [True]


def test_existing_setup_uses_only_backend_verify_command():
    commands = []

    class Runner:
        def run(self, command, **kwargs):
            commands.append(command)

    candidate = release.Release(
        argparse.Namespace(update_existing=True, schemas=release.SCHEMAS), Runner()
    )
    candidate.database_url = "postgresql://fixture"
    candidate.setup()
    assert commands == [[release.sys.executable, "scripts/setup_db.py", "--verify-only"]]


@pytest.mark.parametrize("direct_setup_race", [False, True])
def test_real_postgres_release_locks_and_native_setup(direct_setup_race):
    from psycopg import connect, sql

    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for isolated release PostgreSQL evidence")
    if urlsplit(database_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Release integration contracts require local disposable PostgreSQL")
    nonce = uuid4().hex[:16]
    schemas = (f"langgraph_release_app_{nonce}", f"langgraph_release_checkpoints_{nonce}")
    setup_calls = []
    with connect(database_url, autocommit=True) as inspection:
        assert not inspection.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)", (list(schemas),)
        ).fetchall()

        class ObservingRunner(release.Runner):
            def run(self, command, **kwargs):
                if "--require-fresh" in command:
                    for schema in schemas:
                        rows = inspection.execute(
                            "WITH selected AS (SELECT hashtextextended(%s, 0) AS key) "
                            "SELECT a.state, a.backend_xmin FROM pg_locks AS l "
                            "JOIN pg_stat_activity AS a ON a.pid = l.pid CROSS JOIN selected "
                            "WHERE l.locktype = 'advisory' AND l.granted AND l.objsubid = 1 "
                            "AND l.classid = ((selected.key >> 32) & 4294967295)::oid "
                            "AND l.objid = (selected.key & 4294967295)::oid",
                            (f"langgraph:release:{schema}",),
                        ).fetchall()
                        assert rows == [("idle", None)]
                    for key in (
                        f"langgraph:application-migrations:{schemas[0]}",
                        f"langgraph:checkpoint-migrations:{schemas[1]}",
                    ):
                        assert inspection.execute(
                            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (key,)
                        ).fetchone() == (True,)
                        inspection.execute(
                            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (key,)
                        )
                    if direct_setup_race:
                        inspection.execute(
                            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schemas[0]))
                        )
                    setup_calls.append(command)
                return super().run(command, **kwargs)

        candidate = release.Release(
            argparse.Namespace(update_existing=False, schemas=schemas), ObservingRunner()
        )
        candidate.database_url = database_url
        try:
            if direct_setup_race:
                with pytest.raises(release.ReleaseError):
                    candidate.setup()
                assert inspection.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)",
                    (schemas[1],),
                ).fetchone() == (False,)
                assert not inspection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schemas[0],)
                ).fetchall()
            else:
                candidate.setup()
                candidate.args.update_existing = True
                candidate.setup()
                candidate.args.update_existing = False
                with pytest.raises(release.ReleaseError, match="BOTH schema namespaces"):
                    candidate.setup()
            assert len(setup_calls) == 1
        finally:
            for schema in reversed(schemas):
                inspection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )
