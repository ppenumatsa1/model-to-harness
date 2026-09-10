from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import yaml


@pytest.fixture
def setup(monkeypatch, tmp_path):
    lane = next(parent for parent in Path(__file__).parents if (parent / "azure.yaml").exists())
    monkeypatch.syspath_prepend(str(lane / "scripts"))
    import prepare_hosted_eval as helper

    original_root = lane / "infra/foundry-hosted/agent"
    config = yaml.safe_load((original_root / "eval.yaml").read_text())
    rows = [
        json.loads(line)
        for line in (original_root / config["dataset"]["local_uri"]).read_text().splitlines()
    ]
    root = tmp_path / "agent"
    source = root / config["dataset"]["local_uri"]
    source.parent.mkdir(parents=True)
    source.write_text("\n".join(json.dumps(row) for row in rows))
    config_path = root / "eval.yaml"
    config_path.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(helper, "AGENT_ROOT", root)
    monkeypatch.setattr(helper, "ARTIFACT_ROOT", tmp_path / ".azure/release")
    values = {
        "AZURE_ENV_NAME": "maf-dev",
        "AGENT_MODEL_HARNESS_MAF_NAME": helper.SERVICE,
        "AGENT_MODEL_HARNESS_MAF_VERSION": "5",
        "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/maf",
        "DATABASE_URL": "secret-connection-string",
        "LAST_EVAL_ID": "eval_hidden_history_must_not_be_used",
    }
    runner = Mock()
    runner.json.return_value = values
    credential = MagicMock()
    credential.__enter__.return_value = credential
    project = MagicMock()
    project.__enter__.return_value = project
    client = MagicMock()
    client.__enter__.return_value = client
    project.get_openai_client.return_value = client
    order = []
    deployed = {"name": helper.SERVICE, "version": "5", "status": "active"}

    def get_agent(**kwargs):
        order.append("agent")
        return SimpleNamespace(as_dict=lambda: deployed)

    def get_evaluator(*, name, version):
        order.append(name)
        return SimpleNamespace(
            as_dict=lambda: {
                "name": name,
                "version": version,
                "evaluator_type": "builtin",
                "supported_evaluation_levels": ["turn"],
            }
        )

    def create_group(**kwargs):
        order.append("create")
        return SimpleNamespace(id=f"eval_fresh_{order.count('create')}")

    project.agents.get_version.side_effect = get_agent
    project.beta.evaluators.get_version.side_effect = get_evaluator
    client.evals.create.side_effect = create_group
    credential_factory = Mock(return_value=credential)
    project_factory = Mock(return_value=project)
    monkeypatch.setattr("azure.identity.DefaultAzureCredential", credential_factory)
    monkeypatch.setattr("azure.ai.projects.AIProjectClient", project_factory)
    return SimpleNamespace(
        helper=helper,
        config=config,
        config_path=config_path,
        source=source,
        rows=rows,
        values=values,
        runner=runner,
        credential=credential,
        project=project,
        client=client,
        credential_factory=credential_factory,
        project_factory=project_factory,
        order=order,
        deployed=deployed,
    )


def execute(setup):
    return setup.helper.prepare("maf-dev", "5", setup.config_path, setup.runner)


def test_setup_reproduces_proven_schema_pins_names_and_mappings(setup):
    result = execute(setup)
    definition = setup.client.evals.create.call_args.kwargs
    assert definition["data_source_config"] == {
        "type": "custom",
        "item_schema": {},
        "include_sample_schema": True,
    }
    for criterion, (name, version) in zip(
        definition["testing_criteria"], setup.helper.PINS.items(), strict=True
    ):
        assert criterion == {
            "type": "azure_ai_evaluator",
            "name": name.removeprefix("builtin."),
            "evaluator_name": name,
            "evaluator_version": version,
            "initialization_parameters": {
                "deployment_name": setup.config["options"]["eval_model"],
                "model": setup.config["options"]["eval_model"],
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{sample.output_items}}",
                "tool_calls": "{{sample.tool_calls}}",
                "tool_definitions": "{{sample.tool_definitions}}",
            },
        }
    assert setup.order == ["agent", "builtin.task_completion", "builtin.relevance", "create"]
    request = json.loads(Path(result["request"]).read_text())
    assert set(request) == {
        "projectEndpoint",
        "agentName",
        "agentVersion",
        "evaluationName",
        "runName",
        "evaluatorNames",
        "deploymentName",
        "evaluationId",
        "inputData",
    }
    assert request["evaluationId"] == result["evaluationId"] == "eval_fresh_1"
    assert request["agentVersion"] == "5"
    assert request["agentName"] == setup.helper.SERVICE
    assert request["projectEndpoint"] == setup.values["FOUNDRY_PROJECT_ENDPOINT"]
    assert request["evaluationName"] == request["runName"] == definition["name"]
    assert request["evaluatorNames"] == list(setup.helper.PINS)
    assert request["deploymentName"] == setup.config["options"]["eval_model"]
    assert result["runCreated"] is False
    assert result["nextTool"] == "evaluation_agent_batch_eval_create"
    setup.client.evals.create.assert_called_once()
    setup.client.evals.runs.create.assert_not_called()
    setup.client.responses.create.assert_not_called()
    setup.project.agents.create_version.assert_not_called()


def test_selected_environment_and_context_managers_disable_mutation_retries(setup):
    execute(setup)
    setup.runner.json.assert_called_once()
    call = setup.runner.json.call_args
    assert call.args[0] == [
        "azd",
        "env",
        "get-values",
        "--output",
        "json",
        "--environment",
        "maf-dev",
    ]
    assert "env" not in call.kwargs
    setup.credential_factory.assert_called_once_with(process_timeout=60)
    setup.project_factory.assert_called_once_with(
        endpoint=setup.values["FOUNDRY_PROJECT_ENDPOINT"],
        credential=setup.credential,
        allow_preview=True,
        retry_total=0,
    )
    setup.project.get_openai_client.assert_called_once_with(max_retries=0, timeout=120)
    setup.project.agents.get_version.assert_called_once_with(
        agent_name=setup.helper.SERVICE, agent_version="5"
    )
    for manager in (setup.credential, setup.project, setup.client):
        manager.__exit__.assert_called_once()


def test_cases_preserve_all_reviewed_contracts_but_allocate_fresh_ids(setup):
    original = copy.deepcopy(setup.rows)
    requests = [json.loads(Path(execute(setup)["request"]).read_text()) for _ in range(2)]
    case_ids, command_ids = [], []
    for request in requests:
        assert len(request["inputData"]) == 4
        for before, after in zip(original, request["inputData"], strict=True):
            assert {k: v for k, v in before.items() if k != "query"} == {
                k: v for k, v in after.items() if k != "query"
            }
            command = json.loads(after["query"])
            case_ids.append(command.pop("existing_case_id"))
            command_ids.append(command.pop("idempotency_key"))
            assert command == json.loads(before["query"])
    assert len(set(case_ids + command_ids)) == 16
    assert setup.rows == original
    assert requests[0]["evaluationId"] != requests[1]["evaluationId"]


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.update(evaluationId="eval_hidden"),
        lambda c: c.update(evaluators=["builtin.task_completion", "builtin.relevance"]),
        lambda c: c["evaluators"][0].update(version="18"),
        lambda c: c["evaluators"][1].update(version=12),
        lambda c: c["evaluators"][1].update(name="unknown", version=None),
        lambda c: c["evaluators"][1].update(name="builtin.task_completion", version="19"),
        lambda c: c["evaluators"][0].update(initialization_parameters={"threshold": 0}),
        lambda c: c["options"].update(eval_model=""),
        lambda c: c["options"].update(pass_threshold=0),
        lambda c: c["agent"].update(version="4"),
        lambda c: c.update(max_samples=2),
        lambda c: c["dataset"].update(local_uri="../outside.jsonl"),
    ],
)
def test_invalid_yaml_is_rejected_before_cloud_or_environment_calls(setup, change):
    change(setup.config)
    setup.config_path.write_text(yaml.safe_dump(setup.config))
    with pytest.raises(setup.helper.SetupError):
        execute(setup)
    setup.runner.json.assert_not_called()
    setup.project_factory.assert_not_called()
    setup.client.evals.create.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        lambda rows: rows.pop(),
        lambda rows: rows[1].update(id=rows[0]["id"]),
        lambda rows: rows[3].update(expected_terminal_status="completed_no_refund"),
        lambda rows: rows[2].update(expected_approval_required=False),
        lambda rows: rows[0].update(ground_truth=""),
        lambda rows: rows[0].update(query='{"action":"resume","run_id":"old"}'),
    ],
)
def test_invalid_case_contract_is_rejected_before_mutation(setup, change):
    change(setup.rows)
    setup.source.write_text("\n".join(json.dumps(row) for row in setup.rows))
    with pytest.raises(setup.helper.SetupError):
        execute(setup)
    setup.project_factory.assert_not_called()
    setup.client.evals.create.assert_not_called()


@pytest.mark.parametrize(
    "key,value",
    [
        ("AGENT_MODEL_HARNESS_MAF_VERSION", "4"),
        ("AGENT_MODEL_HARNESS_MAF_NAME", "other-agent"),
        ("AZURE_ENV_NAME", "other-env"),
        ("FOUNDRY_PROJECT_ENDPOINT", "https://untrusted.example/api/projects/maf"),
        ("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com:invalid/api/projects/maf"),
        ("AZURE_AI_PROJECT_ENDPOINT", "https://other.services.ai.azure.com/api/projects/maf"),
    ],
)
def test_invalid_selected_environment_prevents_sdk_creation(setup, key, value):
    setup.values[key] = value
    with pytest.raises(setup.helper.SetupError):
        execute(setup)
    setup.project_factory.assert_not_called()


@pytest.mark.parametrize("key,value", [("version", "4"), ("status", "stopped"), ("name", "other")])
def test_sdk_rejects_inactive_or_mismatched_agent_before_mutation(setup, key, value):
    setup.deployed[key] = value
    with pytest.raises((setup.helper.SetupError, RuntimeError)):
        execute(setup)
    setup.client.evals.create.assert_not_called()
    assert not setup.helper.ARTIFACT_ROOT.exists()


def test_catalog_pin_must_be_verified_before_mutation(setup):
    setup.project.beta.evaluators.get_version.side_effect = lambda **kw: SimpleNamespace(
        as_dict=lambda: {
            "name": kw["name"],
            "version": "wrong",
            "evaluator_type": "builtin",
            "supported_evaluation_levels": ["turn"],
        }
    )
    with pytest.raises(setup.helper.SetupError, match="catalog"):
        execute(setup)
    setup.client.evals.create.assert_not_called()
    assert not setup.helper.ARTIFACT_ROOT.exists()


def test_private_artifacts_and_console_are_safe(setup, monkeypatch, capsys):
    monkeypatch.setattr(setup.helper, "Runner", lambda: setup.runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "prepare_hosted_eval.py",
            "--environment",
            "maf-dev",
            "--version",
            "5",
            "--config",
            str(setup.config_path),
        ],
    )
    setup.helper.main()
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    output = Path(summary["request"])
    assert output.parent.stat().st_mode & 0o777 == 0o700
    assert {path.name for path in output.parent.iterdir()} == {
        "definition.json",
        "input-data.json",
        "group.json",
        "batch-request.json",
    }
    for artifact in output.parent.iterdir():
        assert artifact.stat().st_mode & 0o777 == 0o600
        assert "secret-connection-string" not in artifact.read_text()
        assert "eval_hidden_history" not in artifact.read_text()
    for row in setup.rows:
        assert row["ground_truth"] not in captured.out + captured.err
        assert json.loads(row["query"])["complaint"] not in captured.out + captured.err
    assert "secret-connection-string" not in captured.out + captured.err


def test_artifact_preflight_failure_prevents_group_creation(setup, monkeypatch):
    monkeypatch.setattr(setup.helper, "write_private_json", Mock(side_effect=OSError("private")))
    with pytest.raises(OSError):
        execute(setup)
    setup.client.evals.create.assert_not_called()


def test_partial_post_create_failure_retains_private_group_receipt(setup, monkeypatch):
    write = setup.helper.write_private_json

    def fail_request(path, value):
        if path.name == "batch-request.json":
            raise OSError("private")
        write(path, value)

    monkeypatch.setattr(setup.helper, "write_private_json", fail_request)
    with pytest.raises(setup.helper.SetupError, match="Group eval_fresh_1 was created"):
        execute(setup)
    (receipt,) = setup.helper.ARTIFACT_ROOT.glob("*/group.json")
    assert json.loads(receipt.read_text()) == {"evaluationId": "eval_fresh_1"}
    setup.client.evals.create.assert_called_once()
    setup.client.evals.runs.create.assert_not_called()


def test_main_suppresses_raw_sdk_errors_and_never_retries(setup, monkeypatch, capsys):
    from azure.core.exceptions import AzureError

    setup.client.evals.create.side_effect = AzureError("private-prompt-and-token")
    monkeypatch.setattr(setup.helper, "Runner", lambda: setup.runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "prepare_hosted_eval.py",
            "--environment",
            "maf-dev",
            "--version",
            "5",
            "--config",
            str(setup.config_path),
        ],
    )
    with pytest.raises(SystemExit) as failure:
        setup.helper.main()
    assert "private-prompt-and-token" not in str(failure.value)
    assert "No run was started" in str(failure.value)
    assert capsys.readouterr().out == ""
    setup.client.evals.create.assert_called_once()
