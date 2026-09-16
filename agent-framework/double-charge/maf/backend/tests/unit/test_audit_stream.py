from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from maf_double_charge.api.dependencies import get_repository, get_service
from maf_double_charge.api.routers import streams
from maf_double_charge.application.models import (
    ApprovalResponse,
    DurableEvent,
    RunStatus,
    WorkflowState,
)
from maf_double_charge.projections.workspace import safe_event
from model_to_harness_shared import WorkflowOutcome


def frames(body: str) -> list[dict]:
    result = []
    for block in body.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        fields["data"] = json.loads(fields["data"])
        result.append(fields)
    return result


@pytest.fixture
async def state(repository):
    value = WorkflowState(
        run_id="run-stream",
        case_id="case-stream",
        customer_id="customer-100",
        scenario_id="duplicate-confirmed",
        complaint="I was charged twice.",
        idempotency_key="private-key",
        account_summary={"secret": "private-account"},
        duplicate_evidence={"prompt": "private-prompt"},
    )
    await repository.create_run(value)
    return value


@pytest.fixture
async def client(repository, service):
    app = FastAPI()
    app.include_router(streams.router)
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value


def request():
    return SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))


def event(state, **updates):
    return DurableEvent(
        case_id=state.case_id,
        run_id=state.run_id,
        event_type="approval.recorded",
        summary="Approval recorded.",
        idempotency_key="private-key",
        payload={
            "decision": "approve",
            "reviewer_id": "reviewer",
            "reason": "Evidence checked.\nApproved.",
            "prompt": "private-prompt",
            "checkpoint": {"body": "private-checkpoint"},
            "tool_arguments": {"secret": "private-tool"},
        },
    ).model_copy(update=updates)


async def test_finite_stream_uses_safe_dtos_and_headers(client, repository, state):
    saved = await repository.append_event(event(state))
    await repository.save_memory(
        state.case_id, {"customer_id": "customer-100", "secret": "private"}
    )
    response = await client.get(f"/api/runs/{state.run_id}/events/stream?follow=false")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    audit, snapshot = frames(response.text)
    assert audit == {
        "event": "audit",
        "id": str(saved.sequence),
        "data": safe_event(saved).model_dump(mode="json"),
    }
    assert audit["data"]["payload"]["reason"] == "Evidence checked.\nApproved."
    assert snapshot["event"] == "snapshot"
    assert "id" not in snapshot
    assert snapshot["data"]["memory"] == {"customer_id": "customer-100"}
    assert snapshot["data"]["state"]["complaint"] == state.complaint
    for secret in ("private", "idempotency_key", "account_summary", "duplicate_evidence"):
        assert secret not in response.text


async def test_bounded_replay_and_resume_with_noncontiguous_sequences(
    client, repository, state, monkeypatch
):
    saved = []
    for _ in range(405):
        saved.append(await repository.append_event(event(state)))
        await repository.append_event(event(state, run_id="other-run", case_id="other-case"))
    reads = AsyncMock(wraps=repository.list_events)
    monkeypatch.setattr(repository, "list_events", reads)
    response = await client.get(f"/api/runs/{state.run_id}/events/stream?follow=false")
    audit = [frame for frame in frames(response.text) if frame["event"] == "audit"]
    assert [int(frame["id"]) for frame in audit] == [item.sequence for item in saved]
    assert len({frame["data"]["event_id"] for frame in audit}) == 405
    assert [call.kwargs["limit"] for call in reads.await_args_list] == [200, 200, 200]
    assert [call.kwargs["after"] for call in reads.await_args_list] == [
        0,
        saved[199].sequence,
        saved[399].sequence,
    ]
    cursor = saved[399].sequence
    response = await client.get(
        f"/api/runs/{state.run_id}/events/stream?follow=false&after={saved[2].sequence}",
        headers={"Last-Event-ID": str(cursor)},
    )
    resumed = [frame for frame in frames(response.text) if frame["event"] == "audit"]
    assert [int(frame["id"]) for frame in resumed] == [item.sequence for item in saved[400:]]
    response = await client.get(
        f"/api/runs/{state.run_id}/events/stream?follow=false&after={saved[-1].sequence}",
        headers={"Last-Event-ID": str(cursor)},
    )
    assert [frame["event"] for frame in frames(response.text)] == ["snapshot"]


@pytest.mark.parametrize(
    "query,header",
    [
        ("after=-1", None),
        ("after=nope", None),
        ("after=9223372036854775808", None),
        ("", ""),
        ("", "-1"),
        ("", "1.2"),
        ("", "+1"),
        ("", " 1"),
        ("", "1,2"),
        ("", "9223372036854775808"),
        ("", "1" * 100),
    ],
)
async def test_invalid_cursor_is_rejected_before_streaming(client, state, query, header):
    response = await client.get(
        f"/api/runs/{state.run_id}/events/stream?follow=false&{query}",
        headers={"Last-Event-ID": header} if header is not None else {},
    )
    assert response.status_code == 422
    assert "text/event-stream" not in response.headers["content-type"]


async def test_unknown_run_is_404(client):
    response = await client.get("/api/runs/missing/events/stream?follow=false")
    assert response.status_code == 404
    assert response.json() == {"detail": "run not found"}


async def test_approval_memory_and_state_changes_emit_snapshots_without_audit(
    repository, service, state, monkeypatch
):
    state = state.advance(
        "approval", status=RunStatus.PAUSED, approval_required=True, checkpoint_id="check"
    )
    await repository.save_state(state)
    incoming = request()
    ticks = 0

    async def idle(seconds):
        nonlocal ticks
        assert seconds == 1
        ticks += 1
        if ticks == 1:
            await repository.save_approval(
                state.run_id,
                "check",
                ApprovalResponse(decision="approve", reviewer_id="reviewer", reason="Verified"),
            )
        elif ticks == 2:
            await repository.save_memory(state.case_id, {"fixture_id": "updated-fixture"})
        elif ticks == 3:
            await repository.save_state(state.advance("refund"))
        else:
            incoming.is_disconnected.return_value = True

    monkeypatch.setattr(
        streams, "asyncio", SimpleNamespace(sleep=idle, CancelledError=asyncio.CancelledError)
    )
    response = await streams.audit_stream(incoming, state.run_id, repository, service, after=0)
    body = "".join([chunk async for chunk in response.body_iterator])
    snapshots = frames(body)
    assert [frame["event"] for frame in snapshots] == ["snapshot"] * 4
    assert all("id" not in frame for frame in snapshots)
    assert snapshots[0]["data"]["can_record_approval"] is True
    assert snapshots[1]["data"]["approval"]["reason"] == "Verified"
    assert snapshots[1]["data"]["can_resume"] is True
    assert snapshots[1]["data"]["can_record_approval"] is False
    assert snapshots[2]["data"]["memory"] == {"fixture_id": "updated-fixture"}
    assert snapshots[3]["data"]["state"]["current_step"] == "refund"
    assert await repository.list_events(state.run_id) == []


async def test_follow_does_not_stop_at_terminal_event_and_emits_late_outcome(
    repository, service, state, monkeypatch
):
    await repository.append_event(event(state, event_type="run.completed"))
    incoming = request()
    late_outcome = WorkflowOutcome(
        case_id=state.case_id,
        run_id=state.run_id,
        duplicate_decision="not_found",
        policy_decision="not_evaluated",
        approval_decision="not_required",
        refund_status="not_requested",
        notification_status="not_sent",
        terminal_status="completed_no_refund",
    )
    ticks = 0

    async def idle(_seconds):
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            await repository.save_outcome(late_outcome)
        elif ticks == 2:
            await repository.append_event(event(state, event_type="maf.native.completed"))
        else:
            incoming.is_disconnected.return_value = True

    monkeypatch.setattr(
        streams, "asyncio", SimpleNamespace(sleep=idle, CancelledError=asyncio.CancelledError)
    )
    response = await streams.audit_stream(incoming, state.run_id, repository, service, after=0)
    result = frames("".join([chunk async for chunk in response.body_iterator]))
    assert [frame["event"] for frame in result] == ["audit", "snapshot", "snapshot", "audit"]
    assert result[1]["data"]["outcome"] is None
    assert result[2]["data"]["outcome"] == late_outcome.model_dump(mode="json")
    assert result[3]["data"]["event_type"] == "maf.native.completed"


async def test_idle_heartbeat_deduplicates_snapshots(repository, service, state, monkeypatch):
    incoming = request()
    clock = 0

    async def idle(_seconds):
        nonlocal clock
        clock += 15
        if clock == 30:
            incoming.is_disconnected.return_value = True

    monkeypatch.setattr(streams, "monotonic", lambda: clock)
    monkeypatch.setattr(
        streams, "asyncio", SimpleNamespace(sleep=idle, CancelledError=asyncio.CancelledError)
    )
    response = await streams.audit_stream(incoming, state.run_id, repository, service, after=0)
    chunks = [chunk async for chunk in response.body_iterator]
    assert len(chunks) == 2
    assert chunks[0].startswith("event: snapshot\n")
    assert chunks[1] == ": keepalive\n\n"


async def test_disconnect_stops_before_reads(repository, service, state, monkeypatch):
    incoming = request()
    incoming.is_disconnected.return_value = True
    reads = AsyncMock(wraps=repository.list_events)
    monkeypatch.setattr(repository, "list_events", reads)
    response = await streams.audit_stream(incoming, state.run_id, repository, service, after=0)
    assert [chunk async for chunk in response.body_iterator] == []
    reads.assert_not_awaited()


async def test_disconnect_during_replay_stops_remaining_batch(repository, service, state):
    await repository.append_event(event(state))
    await repository.append_event(event(state))
    incoming = request()
    response = await streams.audit_stream(incoming, state.run_id, repository, service, after=0)
    assert (await anext(response.body_iterator)).startswith("event: audit\n")
    incoming.is_disconnected.return_value = True
    with pytest.raises(StopAsyncIteration):
        await anext(response.body_iterator)


async def test_cancel_during_idle_propagates_without_error_frame(
    repository, service, state, monkeypatch
):
    sleeping = asyncio.Event()

    async def idle(_seconds):
        sleeping.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        streams, "asyncio", SimpleNamespace(sleep=idle, CancelledError=asyncio.CancelledError)
    )
    response = await streams.audit_stream(request(), state.run_id, repository, service, after=0)
    assert (await anext(response.body_iterator)).startswith("event: snapshot\n")
    pending = asyncio.create_task(anext(response.body_iterator))
    await asyncio.wait_for(sleeping.wait(), timeout=1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    with pytest.raises(StopAsyncIteration):
        await anext(response.body_iterator)


async def test_stream_failure_is_safe_error_not_silent_empty_response(
    client, repository, state, monkeypatch
):
    monkeypatch.setattr(
        repository,
        "list_events",
        AsyncMock(side_effect=RuntimeError("postgres://secret:password@internal/prompt")),
    )
    response = await client.get(f"/api/runs/{state.run_id}/events/stream?follow=false")
    assert frames(response.text) == [
        {
            "event": "error",
            "data": {"message": "Live updates are unavailable. Reconnect."},
        }
    ]
    assert "secret" not in response.text
