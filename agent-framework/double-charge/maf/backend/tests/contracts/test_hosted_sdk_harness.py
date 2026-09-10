from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core.exceptions import AzureError


@pytest.fixture
def harness(monkeypatch):
    lane = next(parent for parent in Path(__file__).parents if (parent / "azure.yaml").exists())
    monkeypatch.syspath_prepend(str(lane / "scripts"))
    import hosted_harness

    return hosted_harness


@pytest.mark.parametrize("failure", [None, "create", "conversation", "response", "parse", "stop"])
def test_sdk_commands_pin_version_and_always_stop_owned_session(harness, failure):
    project = Mock()
    client = Mock()
    project.agents.create_session.side_effect = lambda **kwargs: SimpleNamespace(
        agent_session_id=kwargs["agent_session_id"],
        version_indicator=kwargs["version_indicator"],
        status="active",
    )
    client.conversations.create.return_value.id = "new-conversation"
    client.responses.create.return_value.model_dump_json.return_value = json.dumps(
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": '{"run_id": "run-test"}'},
                    ],
                }
            ],
        }
    )
    if failure == "create":
        project.agents.create_session.side_effect = AzureError("private detail")
    elif failure == "conversation":
        client.conversations.create.side_effect = AzureError("private detail")
    elif failure == "response":
        client.responses.create.side_effect = AzureError("private detail")
    elif failure == "parse":
        client.responses.create.return_value.model_dump_json.return_value = '{"status": "failed"}'
    elif failure == "stop":
        project.agents.stop_session.side_effect = AzureError("private detail")

    command = {"action": "resume", "run_id": "run-test"}
    if failure:
        with pytest.raises((AzureError, harness.ReleaseError)) as error:
            harness.invoke_sdk(project, client, "5", command)
        if failure == "stop":
            assert "private" not in str(error.value)
    else:
        assert harness.invoke_sdk(project, client, "5", command) == {"run_id": "run-test"}
    created = project.agents.create_session.call_args.kwargs
    assert created["version_indicator"].agent_version == "5"
    assert created["agent_session_id"].startswith("maf-check-")
    project.agents.stop_session.assert_called_once_with(
        agent_name=harness.SERVICE,
        session_id=created["agent_session_id"],
    )
    assert client.responses.create.call_count <= 1
    if not failure:
        client.responses.create.assert_called_once_with(
            input=json.dumps(command),
            conversation="new-conversation",
            stream=False,
            extra_body={"agent_session_id": created["agent_session_id"]},
        )


@pytest.mark.parametrize("mismatch", ["version", "id", "status"])
def test_sdk_session_must_match_requested_identity_and_be_ready(harness, mismatch):
    from azure.ai.projects.models import VersionRefIndicator

    project = Mock()
    client = Mock()
    project.agents.create_session.side_effect = lambda **kwargs: SimpleNamespace(
        agent_session_id="other" if mismatch == "id" else kwargs["agent_session_id"],
        version_indicator=VersionRefIndicator(agent_version="4" if mismatch == "version" else "5"),
        status="failed" if mismatch == "status" else "active",
    )
    with pytest.raises(harness.ReleaseError, match="not ready"):
        harness.invoke_sdk(project, client, "5", {"action": "start"})
    client.responses.create.assert_not_called()
    project.agents.stop_session.assert_called_once()


@pytest.mark.parametrize("status", ["active", "failed"])
def test_sdk_entrypoint_checks_serialized_status_and_disables_request_retries(
    harness,
    monkeypatch,
    status,
):
    from azure.ai.projects.models import AgentVersionDetails

    credential = Mock()
    project = Mock()
    project.agents.get_version.return_value = AgentVersionDetails(
        {
            "version": "5",
            "status": status,
        }
    )
    credential_factory = Mock()
    credential_factory.return_value.__enter__ = Mock(return_value=credential)
    credential_factory.return_value.__exit__ = Mock(return_value=False)
    project_factory = Mock()
    project_factory.return_value.__enter__ = Mock(return_value=project)
    project_factory.return_value.__exit__ = Mock(return_value=False)
    project.get_openai_client.return_value.__enter__ = Mock()
    project.get_openai_client.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("azure.identity.DefaultAzureCredential", credential_factory)
    monkeypatch.setattr("azure.ai.projects.AIProjectClient", project_factory)
    monkeypatch.setattr(
        harness,
        "environment_values",
        lambda *_: {
            "AGENT_MODEL_HARNESS_MAF_VERSION": "5",
            "FOUNDRY_PROJECT_ENDPOINT": "https://project.example",
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "hosted_harness.py",
            "--version",
            "5",
            "--transport",
            "sdk",
            "--smoke",
        ],
    )
    scenarios = Mock()
    monkeypatch.setattr(harness, "run_scenarios", scenarios)
    if status == "active":
        harness.main()
        assert scenarios.call_args.args[1] == "5"
        assert scenarios.call_args.kwargs["smoke"]
    else:
        with pytest.raises(harness.ReleaseError, match="not active"):
            harness.main()
        scenarios.assert_not_called()
    credential_factory.assert_called_once_with(process_timeout=60)
    project_factory.assert_called_once_with(
        endpoint="https://project.example",
        credential=credential,
        allow_preview=True,
        retry_total=0,
    )
    project.get_openai_client.assert_called_once_with(
        agent_name=harness.SERVICE,
        max_retries=0,
        timeout=300,
    )
    credential_factory.return_value.__exit__.assert_called_once()
    project_factory.return_value.__exit__.assert_called_once()
    project.get_openai_client.return_value.__exit__.assert_called_once()
