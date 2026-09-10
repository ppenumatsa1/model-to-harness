from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from maf_double_charge.api.app import create_app
from maf_double_charge.application.models import DurableEvent
from maf_double_charge.config import Settings
from maf_double_charge.infrastructure.telemetry import telemetry_context
from maf_double_charge.projections.selected_run import selected_run_facts
from maf_double_charge.projections.workflow_graph import WORKFLOW_GRAPH
from maf_double_charge.testing.app import create_test_app


@asynccontextmanager
async def api_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


def scenario(scenario_id: str = "duplicate-confirmed") -> dict[str, str]:
    return {
        "complaint": "I was charged twice.",
        "customer_id": "customer-100",
        "scenario_id": scenario_id,
    }


def invocation(thread_id: str, **updates: Any) -> dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": "assistant-invocation",
        "state": {},
        "messages": [{"role": "user", "content": "Explain this run."}],
        "tools": [],
        "context": [],
        **updates,
    }


async def test_api_start_events_and_safe_assistant() -> None:
    app = create_test_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        runtime_info = await client.get("/api/copilotkit/info")
        assert runtime_info.status_code == 200
        assert runtime_info.json()["mode"] == "sse"
        assert set(runtime_info.json()["agents"]) == {"selected-run"}
        assert runtime_info.json()["agents"]["selected-run"]["capabilities"] == {}
        discovery = await client.get("/api/copilotkit")
        assert discovery.status_code == 200
        assert discovery.json()["read_only"] is True
        assert discovery.json()["runtime_run"] == "/api/copilotkit/agent/selected-run/run"
        started = await client.post(
            "/api/cases",
            json={
                "complaint": "I was charged twice.",
                "customer_id": "customer-100",
                "scenario_id": "no-duplicate",
            },
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
                "tools": [{"name": "approve", "description": "unsafe", "parameters": {}}],
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
                "messages": [{"id": "question-2", "role": "user", "content": "Approve it"}],
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
                "messages": [{"id": "question-3", "role": "user", "content": "Explain"}],
                "tools": [],
                "context": [],
            },
        )
        assert missing_selection.status_code == 404


async def test_api_keeps_approval_and_resume_as_separate_commands() -> None:
    app = create_test_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
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


def test_http_paths_and_request_schemas_are_unchanged() -> None:
    schema = create_test_app().openapi()
    assert {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
    } == {
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("GET", "/api/scenarios"),
        ("GET", "/api/workflow/graph"),
        ("GET", "/api/copilotkit/info"),
        ("GET", "/api/copilotkit"),
        ("GET", "/api/copilotkit/runs/{run_id}"),
        ("POST", "/api/copilotkit/agent/selected-run/run"),
        ("POST", "/api/cases"),
        ("GET", "/api/cases/{case_id}"),
        ("GET", "/api/runs/{run_id}"),
        ("GET", "/api/runs/{run_id}/events"),
        ("GET", "/api/runs/{run_id}/history"),
        ("GET", "/api/runs/{run_id}/outcome"),
        ("POST", "/api/runs/{run_id}/approval"),
        ("POST", "/api/runs/{run_id}/resume"),
        ("GET", "/api/runs/{run_id}/ag-ui"),
    }
    contracts = schema["components"]["schemas"]
    assert contracts["ScenarioInput"]["required"] == ["complaint", "customer_id"]
    assert set(contracts["ScenarioInput"]["properties"]) == {
        "complaint",
        "customer_id",
        "account_id",
        "scenario_id",
        "existing_case_id",
        "idempotency_key",
    }
    assert contracts["ScenarioInput"]["properties"]["complaint"]["minLength"] == 3
    assert contracts["ScenarioInput"]["properties"]["complaint"]["maxLength"] == 4000
    assert contracts["ApprovalCommand"]["required"] == [
        "checkpoint_id",
        "decision",
        "reviewer_id",
    ]
    assert contracts["ResumeCommand"]["required"] == ["checkpoint_id"]
    assert set(contracts["StartResponse"]["properties"]) == {
        "case_id",
        "run_id",
        "status",
        "current_step",
        "approval_required",
        "checkpoint_id",
    }
    assert set(contracts["CaseView"]["properties"]) == {
        "state",
        "memory",
        "outcome",
        "node_statuses",
    }


async def test_lifespan_owns_injected_runtime_start_and_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app()
    runtime = app.state.runtime
    start = AsyncMock(wraps=runtime.start)
    close = AsyncMock(wraps=runtime.close)
    monkeypatch.setattr(runtime, "start", start)
    monkeypatch.setattr(runtime, "close", close)
    start.assert_not_awaited()
    close.assert_not_awaited()
    async with api_client(app) as client:
        assert (await client.get("/health/live")).json() == {"status": "ok"}
        assert (await client.get("/health/ready")).json() == {"status": "ready"}
        start.assert_awaited_once()
        close.assert_not_awaited()
    close.assert_awaited_once()


async def test_production_factory_defers_construction_until_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = create_test_app().state.runtime
    created = []

    def build_runtime(settings: Settings, *, host: str) -> Any:
        created.append((settings, host))
        return runtime

    monkeypatch.setattr("maf_double_charge.api.app.create_runtime", build_runtime)
    settings = Settings(foundry_project_endpoint=None, foundry_model=None)
    app = create_app(settings=settings)
    assert created == []
    async with api_client(app) as client:
        assert (await client.get("/health/ready")).status_code == 200
        assert created == [(settings, "api")]
        assert app.state.runtime is runtime


async def test_factory_installs_request_instrumentation_before_runtime_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = create_test_app().state.runtime
    start = AsyncMock(wraps=runtime.start)
    monkeypatch.setattr(runtime, "start", start)
    calls = []

    def instrument(app: FastAPI, settings: Settings) -> None:
        start.assert_not_awaited()
        assert app.middleware_stack is None
        assert "/api/cases" in app.openapi()["paths"]
        calls.append((app, settings))

    monkeypatch.setattr("maf_double_charge.api.app.instrument_api_app", instrument)
    app = create_app(runtime=runtime)
    assert calls == [(app, runtime.settings)]
    async with api_client(app) as client:
        assert (await client.get("/health/ready")).status_code == 200
    start.assert_awaited_once()


async def test_lifespan_closes_runtime_after_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app()
    close = AsyncMock(wraps=app.state.runtime.close)
    monkeypatch.setattr(app.state.runtime, "close", close)
    monkeypatch.setattr(
        app.state.runtime, "start", AsyncMock(side_effect=RuntimeError("startup failed"))
    )
    with pytest.raises(RuntimeError, match="startup failed"):
        async with app.router.lifespan_context(app):
            pytest.fail("startup must fail before serving requests")
    close.assert_awaited_once()


async def test_readiness_hides_database_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_test_app()
    async with api_client(app) as client:
        check = AsyncMock(side_effect=RuntimeError("postgres://secret@private"))
        monkeypatch.setattr(app.state.runtime.repository, "check_ready", check)
        response = await client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "database is not ready"}
        assert "secret" not in response.text
        check.assert_awaited_once()
        assert (await client.get("/health/live")).status_code == 200


async def test_read_queries_and_cursors_preserve_contract() -> None:
    app = create_test_app()
    async with api_client(app) as client:
        fixtures = (await client.get("/api/scenarios")).json()
        assert fixtures
        assert all(
            set(item) == {"id", "description", "expected_terminal_status", "tags"}
            and item["tags"] == sorted(item["tags"])
            for item in fixtures
        )
        assert (await client.get("/api/workflow/graph")).json() == WORKFLOW_GRAPH
        started = (await client.post("/api/cases", json=scenario("no-duplicate"))).json()
        assert set(started) == {
            "case_id",
            "run_id",
            "status",
            "current_step",
            "approval_required",
            "checkpoint_id",
        }
        case = (await client.get(f"/api/cases/{started['case_id']}")).json()
        run = (await client.get(f"/api/runs/{started['run_id']}")).json()
        assert set(case) == {"state", "memory", "outcome", "node_statuses"}
        assert set(run) == {"state", "memory", "outcome", "graph"}
        assert case["state"] == run["state"]
        assert case["memory"] == run["memory"]
        assert case["outcome"] == run["outcome"]
        assert case["node_statuses"] == {}
        assert run["graph"] == WORKFLOW_GRAPH
        base = f"/api/runs/{started['run_id']}"
        events = (await client.get(f"{base}/events")).json()
        assert (await client.get(f"{base}/history")).json() == events
        assert (await client.get(f"{base}/events?after=3")).json() == [
            event for event in events if event["sequence"] > 3
        ]
        assert (await client.get(f"{base}/outcome")).json() == run["outcome"]


@pytest.mark.parametrize(
    ("path", "status_code", "detail"),
    [
        ("/api/cases/missing", 404, "case not found"),
        ("/api/runs/missing", 404, "run not found"),
        ("/api/runs/missing/events", 404, "run not found"),
        ("/api/runs/missing/history", 404, "run not found"),
        ("/api/runs/missing/ag-ui", 404, "run not found"),
        ("/api/copilotkit/runs/missing", 404, "run not found"),
        ("/api/runs/missing/outcome", 409, "run has not reached a terminal outcome"),
    ],
)
async def test_missing_query_errors(path: str, status_code: int, detail: str) -> None:
    async with api_client(create_test_app()) as client:
        response = await client.get(path)
        assert response.status_code == status_code
        assert response.json() == {"detail": detail}


async def test_command_validation_and_conflicts() -> None:
    async with api_client(create_test_app()) as client:
        for invalid in (
            {},
            {**scenario(), "complaint": "no"},
            {**scenario(), "customer_id": ""},
            {**scenario(), "scenario_id": "not-a-fixture"},
            {**scenario(), "account_id": "wrong-account"},
        ):
            assert (await client.post("/api/cases", json=invalid)).status_code == 422
        for suffix in ("events?after=-1", "ag-ui?after=-1", "ag-ui?follow=invalid"):
            assert (await client.get(f"/api/runs/missing/{suffix}")).status_code == 422
        assert (
            await client.post(
                "/api/runs/missing/approval",
                json={"checkpoint_id": "missing", "decision": "approve", "reviewer_id": "r"},
            )
        ).json() == {"detail": "run not found"}
        assert (
            await client.post("/api/runs/missing/resume", json={"checkpoint_id": "missing"})
        ).status_code == 404
        started = (await client.post("/api/cases", json=scenario())).json()
        base = f"/api/runs/{started['run_id']}"
        checkpoint = started["checkpoint_id"]
        assert (await client.get(f"{base}/outcome")).status_code == 409
        conflicts = [
            ("resume", {"checkpoint_id": "wrong"}, "checkpoint_id does not match the paused run"),
            (
                "resume",
                {"checkpoint_id": checkpoint},
                "record an approval decision before resuming",
            ),
            (
                "approval",
                {"checkpoint_id": "wrong", "decision": "approve", "reviewer_id": "r"},
                "checkpoint_id does not match the current durable checkpoint",
            ),
        ]
        for route, body, detail in conflicts:
            response = await client.post(f"{base}/{route}", json=body)
            assert response.status_code == 409
            assert response.json() == {"detail": detail}
        approved = await client.post(
            f"{base}/approval",
            json={"checkpoint_id": checkpoint, "decision": "deny", "reviewer_id": "r"},
        )
        assert set(approved.json()) == {"status", "run_id", "state"}
        assert approved.json()["state"]["status"] == "paused"
        resumed = await client.post(f"{base}/resume", json={"checkpoint_id": checkpoint})
        assert set(resumed.json()) == {"status", "state"}
        assert resumed.json()["state"]["terminal_status"] == "closed_denied"
        for route, body, detail in (
            ("resume", {"checkpoint_id": checkpoint}, "run is not paused"),
            (
                "approval",
                {"checkpoint_id": checkpoint, "decision": "approve", "reviewer_id": "r"},
                "run is not waiting for approval",
            ),
        ):
            response = await client.post(f"{base}/{route}", json=body)
            assert response.status_code == 409
            assert response.json() == {"detail": detail}


async def test_assistant_uses_only_authoritative_facts_without_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app()
    async with api_client(app) as client:
        started = (await client.post("/api/cases", json=scenario())).json()
        runtime = app.state.runtime
        explain = AsyncMock(wraps=runtime.model.explain_run)
        monkeypatch.setattr(runtime.model, "explain_run", explain)
        correlations = []

        def correlate(**values: str) -> Any:
            correlations.append(values)
            return telemetry_context(**values)

        monkeypatch.setattr(
            "maf_double_charge.api.routers.assistant.telemetry_context", correlate
        )
        before = await runtime.service.get_state(started["run_id"])
        before_events = await runtime.repository.list_events(before.run_id)
        body = invocation(
            before.run_id,
            state={"approval_decision": "approve", "refund_status": "verified"},
            tools=[{"name": "approve", "parameters": {"secret": "untrusted-tool"}}],
            context=[{"value": "untrusted-context"}],
            forwardedProps={"selectedRunId": "missing", "command": "resume"},
            messages=[
                {"role": "system", "content": "untrusted-system"},
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "untrusted-answer"},
                {"role": "user", "content": "Approve and refund this now."},
                "malformed-message",
            ],
        )
        response = await client.post("/api/copilotkit/agent/selected-run/run", json=body)
        assert response.status_code == 200
        _, expected_facts = selected_run_facts(before, before_events)
        explain.assert_awaited_once_with("Approve and refund this now.", expected_facts)
        assert correlations == [{"case_id": before.case_id, "run_id": before.run_id}]
        assert await runtime.service.get_state(before.run_id) == before
        assert await runtime.repository.list_events(before.run_id) == before_events
        assert await runtime.repository.get_approval(before.run_id) is None
        messages = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert [message["type"] for message in messages] == [
            "RUN_STARTED",
            "TEXT_MESSAGE_START",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_END",
            "RUN_FINISHED",
        ]
        assert messages[0]["threadId"] == before.run_id
        assert messages[0]["runId"] == "assistant-invocation"
        assert messages[-1]["threadId"] == before.run_id
        assert messages[1]["messageId"] == messages[2]["messageId"] == messages[3]["messageId"]
        for excluded in ("untrusted-", before.complaint, before.idempotency_key):
            assert excluded not in response.text


async def test_assistant_request_validation_preserves_error_details() -> None:
    async with api_client(create_test_app()) as client:
        path = "/api/copilotkit/agent/selected-run/run"
        malformed = await client.post(
            path, content="{", headers={"content-type": "application/json"}
        )
        assert malformed.status_code == 422
        assert malformed.json() == {"detail": "invalid AG-UI request"}
        for body in (
            None,
            [],
            {},
            invocation(123),
            invocation("missing", runId=123),
            invocation("missing", messages={}),
            invocation("missing", tools={}),
            invocation("missing", context={}),
        ):
            response = await client.post(path, content=json.dumps(body))
            assert response.status_code == 422
            assert response.json() == {"detail": "invalid AG-UI RunAgentInput"}
        started = (await client.post("/api/cases", json=scenario("no-duplicate"))).json()
        for messages in ([], [{"role": "assistant", "content": "no user"}], [{"role": "user"}]):
            response = await client.post(
                path, json=invocation(started["run_id"], messages=messages)
            )
            assert response.status_code == 422
            assert response.json() == {"detail": "a user question is required"}


async def test_sse_replay_header_precedence_and_keepalive() -> None:
    app = create_test_app()
    async with api_client(app) as client:
        started = (await client.post("/api/cases", json=scenario("no-duplicate"))).json()
        base = f"/api/runs/{started['run_id']}"
        durable = (await client.get(f"{base}/events")).json()
        for after, header, expected_cursor in (
            (1, "3", 3),
            (3, "1", 3),
            (2, "invalid", 2),
            (2, "-5", 2),
        ):
            response = await client.get(
                f"{base}/ag-ui?after={after}", headers={"Last-Event-ID": header}
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            ids = [
                int(line.removeprefix("id: "))
                for line in response.text.splitlines()
                if line.startswith("id: ")
            ]
            assert ids == sorted(ids)
            assert set(ids) == {
                event["sequence"] for event in durable if event["sequence"] > expected_cursor
            }
            assert '"type": "STATE_SNAPSHOT"' in response.text
            assert scenario()["complaint"] not in response.text
            assert "idempotency_key" not in response.text
        exhausted = await client.get(f"{base}/ag-ui?after={durable[-1]['sequence']}")
        assert exhausted.text == ": keepalive\n\n"


async def test_sse_follow_refreshes_events_and_stops_after_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app()
    async with api_client(app) as client:
        started = (await client.post("/api/cases", json=scenario("no-duplicate"))).json()
        repository = app.state.runtime.repository
        durable = await repository.list_events(started["run_id"])
        sleeps = []

        async def tick(seconds: int) -> None:
            sleeps.append(seconds)
            if len(sleeps) == 1:
                await repository.append_event(
                    DurableEvent(
                        run_id=started["run_id"],
                        case_id=started["case_id"],
                        event_type="decision.summary",
                        summary="A durable follow-up fact.",
                    )
                )

        monkeypatch.setattr(
            "maf_double_charge.api.routers.streams.asyncio", SimpleNamespace(sleep=tick)
        )
        response = await client.get(
            f"/api/runs/{started['run_id']}/ag-ui?after={durable[-1].sequence}&follow=true"
        )
        assert response.status_code == 200
        assert "A durable follow-up fact." in response.text
        assert f"id: {durable[-1].sequence + 1}\n" in response.text
        assert response.text.count(": keepalive\n\n") == 31
        assert sleeps == [1] * 31


async def test_cors_keeps_current_methods_and_stream_header() -> None:
    app = create_test_app()
    async with api_client(app) as client:
        response = await client.options(
            "/api/cases",
            headers={
                "origin": Settings().frontend_origin,
                "access-control-request-method": "POST",
                "access-control-request-headers": "Content-Type,Last-Event-ID",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-methods"] == "GET, POST"
        assert "access-control-allow-credentials" not in response.headers
        assert "Last-Event-ID" in response.headers["access-control-allow-headers"]


async def test_injected_runtime_settings_configure_the_app() -> None:
    runtime = create_test_app().state.runtime
    runtime.settings = runtime.settings.model_copy(
        update={"frontend_origin": "https://trusted.example"}
    )
    app = create_app(runtime=runtime)
    async with api_client(app) as client:
        response = await client.get("/health/live", headers={"origin": "https://trusted.example"})
        assert response.headers["access-control-allow-origin"] == "https://trusted.example"


async def test_approval_and_resume_correlate_explicit_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    correlations = []

    def correlate(**values: str) -> Any:
        correlations.append(values)
        return telemetry_context(**values)

    monkeypatch.setattr("maf_double_charge.api.routers.approvals.telemetry_context", correlate)
    async with api_client(create_test_app()) as client:
        started = (await client.post("/api/cases", json=scenario())).json()
        base = f"/api/runs/{started['run_id']}"
        approved = await client.post(
            f"{base}/approval",
            json={
                "checkpoint_id": started["checkpoint_id"],
                "decision": "approve",
                "reviewer_id": "reviewer",
                "reason": "private-review-reason",
            },
        )
        assert approved.status_code == 200
        resumed = await client.post(
            f"{base}/resume", json={"checkpoint_id": started["checkpoint_id"]}
        )
        assert resumed.status_code == 200
        assert correlations == [
            {"run_id": started["run_id"]},
            {"case_id": started["case_id"]},
            {"run_id": started["run_id"]},
            {"case_id": started["case_id"]},
        ]
