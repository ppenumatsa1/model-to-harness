from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tomllib
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


def test_apply_rejects_dirty_commit(modules):
    release, *_ = modules
    args = release.parser().parse_args(["--apply", "--source-commit", "a" * 40])
    runner = Mock()
    runner.run.side_effect = ["a" * 40, "a" * 40, " M backend/runtime.py"]
    with pytest.raises(release.ReleaseError):
        release.Release(args, runner).source_commit()


def configured_release(
    release, monkeypatch, *, apply=False, foundation=False, migration_error=False
):
    args = release.parser().parse_args(
        (["--apply", "--source-commit", "a" * 40] if apply else [])
        + (["--foundation"] if foundation else [])
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
        "postgresSchema": "maf_double_charge",
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

    def deploy(parameters, *, preview, suffix=""):
        if preview:
            operations.append("preview")
            assert parameters["postgresSchema"] == release.SCHEMA
            return {"changes": []}
        operations.append("foundation" if suffix else "rollout")
        assert parameters["postgresSchema"] == ("maf_double_charge" if suffix else release.SCHEMA)
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
    assert command[command.index("--version") + 1] == "4"
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
                    "customer_id": identifier,
                    "existing_case_id": identifier,
                    "idempotency_key": identifier,
                },
                identifier,
            )
            assert started["case_id"] == identifier
            result = started
            if decision:
                assert started["status"] == "paused" and started["approval_required"]
                checkpoint = {
                    "run_id": started["run_id"],
                    "checkpoint_id": started["checkpoint_id"],
                }
                recorded = await adapter._execute(
                    {
                        **checkpoint,
                        "action": "approval",
                        "decision": decision,
                        "reviewer_id": identifier,
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
    finally:
        await runtime.close()


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

    async def execute(run_id, command):
        assert run_id == state.run_id
        observed.update(current_log_context())
        return state

    service = SimpleNamespace(
        get_state=AsyncMock(return_value=state),
        get_outcome=AsyncMock(return_value=None),
        record_approval=AsyncMock(side_effect=execute),
        resume=AsyncMock(side_effect=execute),
    )
    runtime = SimpleNamespace(
        service=service, repository=SimpleNamespace(list_events=AsyncMock(return_value=[]))
    )
    monkeypatch.setattr(adapter, "_runtime", AsyncMock(return_value=runtime))
    with telemetry_context(
        conversation_id="platform-conversation", response_id="platform-response"
    ):
        await adapter._execute(
            {
                "action": action,
                "run_id": "requested-run",
                "checkpoint_id": "checkpoint",
                "decision": "approve",
                "reviewer_id": "reviewer",
            },
            "platform-conversation",
        )
    assert service.get_state.call_args_list[0].args == ("requested-run",)
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
