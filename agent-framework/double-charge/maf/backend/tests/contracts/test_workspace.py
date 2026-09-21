from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from maf_double_charge.application.commands import ApprovalCommand
from maf_double_charge.application.models import (
    ApprovalResponse,
    DurableEvent,
    RunStatus,
    WorkflowState,
)
from maf_double_charge.projections.workspace import safe_event
from maf_double_charge.testing.app import create_test_app
from pydantic import ValidationError


def state(number: int) -> WorkflowState:
    return WorkflowState(
        case_id=f"case-{number:03}", run_id=f"run-{number:03}",
        complaint="Two charges for one purchase.", customer_id="customer-100",
        scenario_id="duplicate-confirmed", idempotency_key=f"private-key-{number}",
    )


async def test_history_keyset_ties_new_insert_and_direct_case_selection() -> None:
    app = create_test_app()
    repo = app.state.runtime.repository
    same_time = datetime(2026, 1, 1, tzinfo=UTC)
    for number in range(25):
        item = state(number)
        await repo.create_run(item)
        repo.created_at[item.run_id] = same_time
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        first = (await client.get("/api/cases")).json()
        assert len(first["items"]) == 10 and first["has_more"]
        assert first["items"][0]["run_id"] == "run-024"
        await repo.create_run(state(25))
        second = (await client.get("/api/cases", params={"cursor": first["next_cursor"]})).json()
        third = (await client.get("/api/cases", params={"cursor": second["next_cursor"]})).json()
        ids = [row["run_id"] for page in (first, second, third) for row in page["items"]]
        assert ids == [f"run-{number:03}" for number in reversed(range(25))]
        assert len(third["items"]) == 5 and not third["has_more"]
        assert third["next_cursor"] is None
        selected = await client.get("/api/cases/case-000")
        assert selected.status_code == 200
        assert selected.json()["state"]["run_id"] == "run-000"
        assert "idempotency_key" not in selected.text
        assert "private-key" not in selected.text


@pytest.mark.parametrize("params", [
    {"cursor": "not-a-cursor"}, {"cursor": ""}, {"limit": 0}, {"limit": 101},
    {"cursor": "e30"}, {"cursor": "x" * 513},
])
async def test_invalid_history_request_is_rejected(params) -> None:
    app = create_test_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        assert (await client.get("/api/cases", params=params)).status_code == 422


async def test_safe_workspace_and_legacy_approval_survive_reload(repository, service) -> None:
    repo = repository
    item = state(1).model_copy(update={
        "status": RunStatus.PAUSED, "approval_required": True, "checkpoint_id": "checkpoint-1",
        "account_summary": {"credentials": "PRIVATE"}, "duplicate_evidence": {"prompt": "PRIVATE"},
    })
    await repo.create_run(item)
    await repo.save_memory(item.case_id, {"fixture_id": "duplicate-confirmed", "prompt": "PRIVATE"})
    pending = await service.get_workspace(item.run_id)
    assert pending.can_record_approval and not pending.can_resume
    legacy = ApprovalResponse(decision="approve", reviewer_id="historical-reviewer")
    await repo.save_approval(item.run_id, item.checkpoint_id, legacy)
    reloaded = await service.get_case_workspace(item.case_id)
    assert reloaded.can_resume and not reloaded.can_record_approval
    assert reloaded.approval.reason is None
    assert reloaded.approval.reviewer_id == "historical-reviewer"
    assert "PRIVATE" not in reloaded.model_dump_json()
    assert "private-key" not in reloaded.model_dump_json()


def test_event_projection_is_server_allowlisted() -> None:
    event = DurableEvent(
        run_id="run", case_id="case", sequence=12, event_type="tool.call.succeeded",
        node="submit_refund", summary="Refund recorded.", idempotency_key="PRIVATE",
        payload={"refund_id": "refund-1", "recovered_existing": True, "prompt": "PRIVATE",
                 "arguments": {"password": "PRIVATE"}, "checkpoint": {"raw": "PRIVATE"}},
    )
    projected = safe_event(event)
    assert projected.payload == {"refund_id": "refund-1", "recovered_existing": True}
    assert "PRIVATE" not in projected.model_dump_json()
    unknown = safe_event(event.model_copy(update={"event_type": "future.event"}))
    assert unknown.payload == {} and unknown.sequence == 12


@pytest.mark.parametrize("field,value", [
    ("reason", ""), ("reason", " \n\t"), ("reason", None),
    ("reviewer_id", ""), ("reviewer_id", "  "),
])
def test_new_approvals_require_nonblank_review(field, value) -> None:
    data = {"checkpoint_id": "checkpoint", "decision": "approve",
            "reviewer_id": "reviewer", "reason": "Evidence reviewed."}
    data[field] = value
    with pytest.raises(ValidationError):
        ApprovalCommand.model_validate(data)


async def test_approval_reason_is_persisted_and_exposed_without_resuming() -> None:
    app = create_test_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        started = (await client.post("/api/cases", json={
            "complaint": "I was charged twice.", "customer_id": "customer-100",
            "operator_id": "test-operator",
            "scenario_id": "duplicate-confirmed",
        })).json()
        base = f"/api/runs/{started['run_id']}"
        command = {"checkpoint_id": started["checkpoint_id"], "decision": "approve",
                   "reviewer_id": " reviewer ", "reason": " Validated the evidence. "}
        response = await client.post(f"{base}/approval", json=command)
        assert response.status_code == 200
        assert "idempotency_key" not in response.text
        selected = (await client.get(base)).json()
        assert selected["state"]["status"] == "paused"
        assert selected["state"]["refund_status"] == "not_requested"
        assert selected["approval"]["reason"] == "Validated the evidence."
        assert selected["approval"]["reviewer_id"] == "reviewer"
        assert selected["can_resume"]
        events = (await client.get(f"{base}/events")).json()
        recorded = [event for event in events if event["event_type"] == "approval.recorded"]
        assert recorded[0]["payload"]["reason"] == "Validated the evidence."
        assert (await client.post(f"{base}/approval", json=command)).status_code == 200
        assert (await client.post(f"{base}/approval", json={
            **command, "reason": "A conflicting reason.",
        })).status_code == 409
