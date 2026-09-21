from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.ai.projects.models import VersionRefIndicator
from azure.core.exceptions import HttpResponseError
from openai import APIConnectionError


@pytest.fixture
def harness(monkeypatch):
    lane = next(
        parent for parent in Path(__file__).resolve().parents if (parent / "azure.yaml").exists()
    )
    monkeypatch.syspath_prepend(str(lane / "scripts"))
    import hosted_harness

    monkeypatch.setattr(hosted_harness, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    monkeypatch.setattr(hosted_harness.time, "sleep", lambda seconds: None)
    return hosted_harness


@pytest.mark.parametrize(
    "phase", ["session.create", "session.get", "conversation.create", "response.create"]
)
def test_sdk_failure_reports_safe_phase_and_stops_owned_session(harness, capsys, phase):
    project, client = Mock(), Mock()
    session_id = "maf-check-" + "a" * 32
    project.agents.create_session.return_value = SimpleNamespace(
        agent_session_id=session_id,
        version_indicator=VersionRefIndicator(agent_version="10"),
        status="creating" if phase == "session.get" else "idle",
    )
    error = HttpResponseError(message="private credentials and raw request body")
    error.status_code = 504
    operation = {
        "session.create": project.agents.create_session,
        "session.get": project.agents.get_session,
        "conversation.create": client.conversations.create,
        "response.create": client.responses.create,
    }[phase]
    operation.side_effect = error

    with pytest.raises(HttpResponseError) as caught:
        harness.invoke_sdk(project, client, "10", {"complaint": "private complaint"})

    assert caught.value is error
    assert json.loads(capsys.readouterr().err) == {
        "phase": phase,
        "session_id": session_id,
        "http_status": 504,
        "error_type": "HttpResponseError",
    }
    operation.assert_called_once()
    project.agents.stop_session.assert_called_once_with(
        agent_name=harness.SERVICE, session_id=session_id,
    )
    if phase in {"session.create", "session.get"}:
        client.conversations.create.assert_not_called()
        client.responses.create.assert_not_called()


def test_openai_connection_error_does_not_expose_request(harness, capsys):
    project, client = Mock(), Mock()
    project.agents.create_session.return_value = SimpleNamespace(
        agent_session_id="maf-check-" + "a" * 32,
        version_indicator=VersionRefIndicator(agent_version="10"),
        status="idle",
    )
    client.responses.create.side_effect = APIConnectionError(
        message="private endpoint and credentials", request=Mock(),
    )
    with pytest.raises(APIConnectionError):
        harness.invoke_sdk(project, client, "10", {"complaint": "private complaint"})
    assert json.loads(capsys.readouterr().err) == {
        "phase": "response.create",
        "session_id": "maf-check-" + "a" * 32,
        "http_status": None,
        "error_type": "APIConnectionError",
    }
    client.responses.create.assert_called_once()
    project.agents.stop_session.assert_called_once()
