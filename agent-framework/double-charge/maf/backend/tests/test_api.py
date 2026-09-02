from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from maf_double_charge.api import create_test_app


async def test_api_start_events_and_safe_assistant() -> None:
    app = create_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        runtime_info = await client.get("/api/copilotkit/info")
        assert runtime_info.status_code == 200
        assert runtime_info.json()["mode"] == "sse"
        assert set(runtime_info.json()["agents"]) == {"selected-run"}
        assert runtime_info.json()["agents"]["selected-run"]["capabilities"] == {}
        discovery = await client.get("/api/copilotkit")
        assert discovery.status_code == 200
        assert discovery.json()["read_only"] is True
        assert (
            discovery.json()["runtime_run"]
            == "/api/copilotkit/agent/selected-run/run"
        )
        started = (
            await client.post(
                "/api/cases",
                json={
                    "complaint": "I was charged twice.",
                    "customer_id": "customer-100",
                    "scenario_id": "no-duplicate",
                },
            )
        )
        assert started.status_code == 200
        run_id = started.json()["run_id"]
        run = (await client.get(f"/api/runs/{run_id}")).json()
        assert "selected_memory" not in run["state"]
        assert run["memory"]["last_normalized_issue"] == "I was charged twice."
        events = await client.get(f"/api/runs/{run_id}/events")
        assert events.status_code == 200
        sequences = [event["sequence"] for event in events.json()]
        assert sequences == sorted(sequences)
        bridge = await client.get(f"/api/copilotkit/runs/{run_id}")
        assert bridge.status_code == 200
        assert bridge.json()["read_only"] is True
        serialized_bridge = bridge.text
        assert "I was charged twice." not in serialized_bridge
        assert "idempotency_key" not in serialized_bridge
        assert "checkpoint_id" not in serialized_bridge
        assert (await client.post(f"/api/runs/{run_id}/assistant")).status_code == 404

        runtime = await client.post(
            "/api/copilotkit/agent/selected-run/run",
            json={
                "threadId": run_id,
                "runId": "copilot-invocation",
                "state": {"command": "approve"},
                "messages": [
                    {
                        "id": "question-1",
                        "role": "user",
                        "content": "Why did this case finish?",
                    }
                ],
                "tools": [
                    {"name": "approve", "description": "unsafe", "parameters": {}}
                ],
                "context": [{"description": "unsafe", "value": "secret"}],
                "forwardedProps": {"selectedRunId": "run-untrusted"},
            },
            headers={"accept": "text/event-stream"},
        )
        assert runtime.status_code == 200
        assert runtime.headers["content-type"].startswith("text/event-stream")
        event_stream = runtime.text
        assert '"type": "RUN_STARTED"' in event_stream
        assert '"type": "TEXT_MESSAGE_CONTENT"' in event_stream
        assert '"type": "RUN_FINISHED"' in event_stream
        assert "TOOL_CALL" not in event_stream
        assert "I was charged twice." not in event_stream
        assert "idempotency_key" not in event_stream

        case_selected = await client.post(
            "/api/copilotkit/agent/selected-run/run",
            json={
                "threadId": started.json()["case_id"],
                "runId": "copilot-invocation-2",
                "state": {},
                "messages": [
                    {"id": "question-2", "role": "user", "content": "Approve it"}
                ],
                "tools": [],
                "context": [],
            },
        )
        assert case_selected.status_code == 200

        missing_selection = await client.post(
            "/api/copilotkit/agent/selected-run/run",
            json={
                "threadId": "run-missing",
                "runId": "copilot-invocation-3",
                "state": {},
                "messages": [
                    {"id": "question-3", "role": "user", "content": "Explain"}
                ],
                "tools": [],
                "context": [],
            },
        )
        assert missing_selection.status_code == 404


async def test_api_keeps_approval_and_resume_as_separate_commands() -> None:
    app = create_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        started = (
            await client.post(
                "/api/cases",
                json={
                    "complaint": "I was charged twice.",
                    "customer_id": "customer-100",
                    "scenario_id": "duplicate-confirmed",
                },
            )
        ).json()
        approval = await client.post(
            f"/api/runs/{started['run_id']}/approval",
            json={
                "checkpoint_id": started["checkpoint_id"],
                "decision": "approve",
                "reviewer_id": "api-reviewer",
            },
        )
        assert approval.status_code == 200
        still_paused = (await client.get(f"/api/runs/{started['run_id']}")).json()
        assert still_paused["state"]["status"] == "paused"
        resumed = await client.post(
            f"/api/runs/{started['run_id']}/resume",
            json={"checkpoint_id": started["checkpoint_id"]},
        )
        assert resumed.status_code == 200
        outcome = await client.get(f"/api/runs/{started['run_id']}/outcome")
        assert outcome.json()["terminal_status"] == "completed_refunded"
