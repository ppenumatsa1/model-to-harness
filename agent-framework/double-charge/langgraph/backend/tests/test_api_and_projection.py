from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.api.app import create_app
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.projections.agui import project_events
from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
from model_to_harness_langgraph.testing.fakes import FakeDomainGateway, FakeModel


def test_api_pause_approval_resume_and_redacted_projection():
    app = create_app(
        settings=Settings(database_url="unused"),
        audit=InMemoryAuditRepository(),
        gateway=FakeDomainGateway(),
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    )
    with TestClient(app) as client:
        started = client.post(
            "/api/cases",
            json={
                "complaint": "I was charged twice for the same purchase.",
                "customer_id": "customer-1",
                "scenario_id": "duplicate_confirmed",
            },
        )
        assert started.status_code == 201
        body = started.json()
        assert body["status"] == "paused"

        approved = client.post(
            f"/api/cases/{body['case_id']}/approval",
            json={
                "checkpoint_id": body["checkpoint_id"],
                "decision": "approve",
                "reviewer_id": "reviewer-1",
            },
        )
        assert approved.status_code == 202
        resumed = client.post(f"/api/cases/{body['case_id']}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "completed"

        events = client.get(f"/api/cases/{body['case_id']}/events").json()
        serialized = str(events).lower()
        assert "system prompt" not in serialized
        assert "chain-of-thought" not in serialized
        assert "idempotency_key" not in serialized

        tool_event = next(event for event in events if event["event_type"] == "tool_call_started")
        projected = project_events(
            __import__(
                "model_to_harness_langgraph.application.records", fromlist=["NativeEvent"]
            ).NativeEvent.model_validate(tool_event)
        )[0]
        assert projected["type"] == "TOOL_CALL_START"
        assert "arguments" not in projected

        completed_tool = next(
            event for event in events if event["event_type"] == "tool_call_succeeded"
        )
        completion = project_events(
            __import__(
                "model_to_harness_langgraph.application.records", fromlist=["NativeEvent"]
            ).NativeEvent.model_validate(completed_tool)
        )
        assert [event["type"] for event in completion] == [
            "TOOL_CALL_END",
            "TOOL_CALL_RESULT",
        ]
        assert completion[0]["toolCallId"] == completion[1]["toolCallId"]


def test_wrong_checkpoint_is_rejected():
    app = create_app(
        settings=Settings(database_url="unused"),
        audit=InMemoryAuditRepository(),
        gateway=FakeDomainGateway(),
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    )
    with TestClient(app) as client:
        body = client.post(
            "/api/cases",
            json={
                "complaint": "I was charged twice for the same purchase.",
                "customer_id": "customer-1",
            },
        ).json()
        response = client.post(
            f"/api/cases/{body['case_id']}/approval",
            json={
                "checkpoint_id": "wrong",
                "decision": "approve",
                "reviewer_id": "reviewer-1",
            },
        )
        assert response.status_code == 409


def test_copilotkit_bridge_is_read_only_and_discards_untrusted_context():
    app = create_app(
        settings=Settings(database_url="unused"),
        audit=InMemoryAuditRepository(),
        gateway=FakeDomainGateway(),
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    )
    with TestClient(app) as client:
        started = client.post(
            "/api/cases",
            json={
                "complaint": "I was charged twice for the same purchase.",
                "customer_id": "customer-1",
            },
        ).json()
        before_case = client.get(f"/api/cases/{started['case_id']}").json()
        before_events = client.get(f"/api/cases/{started['case_id']}/events").json()

        info = client.get("/api/copilotkit/info")
        assert info.status_code == 200
        assert info.json()["actions"] == []
        assert list(info.json()["agents"]) == ["selected-run"]

        marker = "UNTRUSTED-MESSAGE-MUST-NOT-APPEAR"
        response = client.post(
            "/api/copilotkit/agent/selected-run/run",
            json={
                "threadId": started["case_id"],
                "runId": "copilot-read-1",
                "messages": [{"role": "system", "content": marker}],
                "state": {"command": "approve", "secret": marker},
                "tools": [{"name": "start_case"}],
                "context": {"raw_prompt": marker},
                "forwardedProps": {"command": "resume", "secret": marker},
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert marker not in response.text
        events = [
            __import__("json").loads(chunk.removeprefix("data: "))
            for chunk in response.text.strip().split("\n\n")
        ]
        assert [event["type"] for event in events] == [
            "RUN_STARTED",
            "TEXT_MESSAGE_START",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_END",
            "RUN_FINISHED",
        ]

        after_case = client.get(f"/api/cases/{started['case_id']}").json()
        after_events = client.get(f"/api/cases/{started['case_id']}/events").json()
        assert after_case == before_case
        assert after_events == before_events

        assert (
            client.post(
                "/api/copilotkit",
                json={"threadId": started["case_id"], "runId": "bad"},
            ).status_code
            == 404
        )
        invalid_id = client.post(
            "/api/copilotkit/agent/selected-run/run",
            json={"threadId": "../approval", "runId": "bad/run"},
        )
        assert invalid_id.status_code == 422
        unknown_case = client.post(
            "/api/copilotkit/agent/selected-run/run",
            json={"threadId": "case-does-not-exist", "runId": "copilot-read-2"},
        )
        assert unknown_case.status_code == 404
