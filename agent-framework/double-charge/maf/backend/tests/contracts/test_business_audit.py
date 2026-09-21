import json

import pytest
from httpx import ASGITransport, AsyncClient
from maf_double_charge.projections.selected_run import selected_run_facts
from maf_double_charge.testing.app import create_test_app


@pytest.mark.parametrize("operator", [None, "", " \t ", 42, "x" * 129])
async def test_start_and_resume_reject_missing_or_invalid_operator(operator):
    app = create_test_app()
    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        data = {"complaint": "Two charges for one purchase.", "customer_id": "customer-100"}
        if operator is not None:
            data["operator_id"] = operator
        assert (await client.post("/api/cases", json=data)).status_code == 422
        resume = {"checkpoint_id": "checkpoint"}
        if operator is not None:
            resume["operator_id"] = operator
        assert (await client.post("/api/runs/missing/resume", json=resume)).status_code == 422
        assert not app.state.runtime.repository.states


@pytest.mark.parametrize(
    ("scenario", "decision", "terminal"),
    [
        ("duplicate-confirmed", "approve", "completed_refunded"),
        ("approval-denied", "deny", "closed_denied"),
        ("retry-safe-refund", "approve", "completed_refunded"),
        ("verification-mismatch", "approve", "manual_review"),
        ("no-duplicate", None, "completed_no_refund"),
        ("transient-failure", None, "failed"),
    ],
)
async def test_business_audit_has_real_actors_and_immutable_outcome(scenario, decision, terminal):
    app = create_test_app()
    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/cases", json={
            "complaint": "Two charges for one purchase.", "customer_id": "customer-100",
            "scenario_id": scenario, "operator_id": "  private-opener  ",
        })
        assert response.status_code == 200
        started = response.json()
        base = f"/api/runs/{started['run_id']}"
        if decision:
            approval = await client.post(f"{base}/approval", json={
                "checkpoint_id": started["checkpoint_id"], "decision": decision,
                "reviewer_id": " private-reviewer ", "reason": "private-review-reason",
            })
            assert approval.status_code == 200
            paused = (await client.get(base)).json()
            assert paused["state"]["refund_status"] == "not_requested"
            assert not any(e["event_type"] == "workflow.continued"
                           for e in (await client.get(f"{base}/events")).json())
            assert (await client.post(f"{base}/resume", json={
                "checkpoint_id": started["checkpoint_id"], "operator_id": " private-resumer ",
            })).status_code == 200
        events = (await client.get(f"{base}/events")).json()
        actors = {"run.started": "private-opener", "approval.recorded": "private-reviewer",
                  "workflow.resumed": "private-resumer"}
        for event in events:
            payload = event["payload"]
            assert payload["audit_version"] == 2
            human = event["event_type"] in actors
            assert payload["actor_type"] == ("human" if human else "system")
            assert payload["actor_id"] == actors.get(event["event_type"], "maf-workflow")
            assert payload["actor_source"] == ("operator_supplied" if human else "system")
        closures = [e for e in events if e["event_type"] in {"run.completed", "run.failed"}]
        assert len(closures) == 1
        assert closures[0]["payload"]["terminal_status"] == terminal
        if decision:
            requested = next(e for e in events if e["event_type"] == "workflow.resumed")
            continued = next(e for e in events if e["event_type"] == "workflow.continued")
            assert requested["sequence"] < continued["sequence"]
        if terminal == "completed_refunded":
            submitted = next(e for e in events if e["event_type"] == "tool.call.succeeded"
                             and e["node"] == "submit_refund")
            verified = next(e for e in events if e["event_type"] == "refund.verification")
            assert submitted["sequence"] < verified["sequence"]
            assert verified["payload"]["verified"] is True
            assert verified["payload"]["matching_refund_count"] == 1
            assert submitted["payload"]["recovered_existing"] == (scenario == "retry-safe-refund")
        repository = app.state.runtime.repository
        state = await repository.get_state(started["run_id"])
        native = await repository.list_events(started["run_id"])
        _, facts = selected_run_facts(state, native)
        for private in (*actors.values(), "private-review-reason"):
            assert private not in json.dumps(facts)
        assert "idempotency_key" not in json.dumps(events)


async def test_resume_request_does_not_claim_continuation_if_runner_fails(monkeypatch):
    from unittest.mock import AsyncMock

    from maf_double_charge.application.commands import ApprovalCommand, ScenarioInput

    app = create_test_app()
    async with app.router.lifespan_context(app):
        service = app.state.runtime.service
        started = await service.start(ScenarioInput(
            operator_id="opener", complaint="Two charges for one purchase.", customer_id="customer"
        ))
        await service.record_approval(started.run_id, ApprovalCommand(
            checkpoint_id=started.checkpoint_id, decision="approve",
            reviewer_id="reviewer", reason="Reviewed.",
        ))
        monkeypatch.setattr(
            service.runner, "resume", AsyncMock(side_effect=RuntimeError("offline"))
        )
        with pytest.raises(RuntimeError, match="offline"):
            await service.resume(started.run_id, started.checkpoint_id, operator_id="resumer")
        events = await service.repository.list_events(started.run_id)
        assert any(e.event_type == "workflow.resumed" for e in events)
        assert not any(e.event_type == "workflow.continued" for e in events)
