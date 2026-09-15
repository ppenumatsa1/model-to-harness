from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.application.records import ApprovalRequest, StartCaseRequest
from model_to_harness_langgraph.application.service import WorkflowService
from model_to_harness_langgraph.graph.runner import DoubleChargeWorkflow
from model_to_harness_langgraph.infrastructure.domain_gateway import ToolResult
from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
from model_to_harness_langgraph.testing.fakes import (
    FakeDomainGateway,
    FakeModel,
    NoDuplicateGateway,
)


def make_service(gateway: FakeDomainGateway | None = None):
    audit = InMemoryAuditRepository()
    gateway = gateway or FakeDomainGateway()
    workflow = DoubleChargeWorkflow(
        audit=audit,
        gateway=gateway,
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    )
    return WorkflowService(workflow, audit), audit, gateway


async def run_approved(scenario_id: str = "duplicate_confirmed"):
    service, audit, gateway = make_service()
    started = await service.start(
        StartCaseRequest(
            complaint="I was charged twice for the same purchase.",
            customer_id="customer-1",
            scenario_id=scenario_id,
        )
    )
    assert started.status == "paused"
    assert started.checkpoint_id
    await service.submit_approval(
        started.case_id,
        ApprovalRequest(
            checkpoint_id=started.checkpoint_id,
            decision="approve",
            reviewer_id="reviewer-1",
        ),
    )
    resumed = await service.resume(started.case_id)
    return service, audit, gateway, started, resumed


async def test_parallel_validation_pauses_and_resumes_to_normalized_outcome():
    service, audit, _, started, resumed = await run_approved()

    assert resumed.status == "completed"
    case = await service.get_case(started.case_id)
    assert case.outcome is not None
    assert case.outcome.duplicate_decision == "confirmed"
    assert case.outcome.policy_decision == "eligible"
    assert case.outcome.approval_decision == "approved"
    assert case.outcome.refund_status == "verified"
    assert case.selected_memory["refund_status"] == "verified"

    event_types = [event.event_type for event in await audit.list_events(started.run_id)]
    assert event_types.index("parallel_branch_started") < event_types.index(
        "parallel_branch_joined"
    )
    assert "checkpoint_created" in event_types
    assert "human_approval_resolved" in event_types
    assert "refund_verification" in event_types


async def test_retry_safe_refund_reuses_one_idempotency_key():
    service, _, gateway, started, resumed = await run_approved("retry_safe_refund")

    assert resumed.status == "completed"
    case = await service.get_case(started.case_id)
    assert case.outcome and case.outcome.refund_status == "verified"
    assert list(gateway.refunds.values()) == ["rf-1"]
    assert next(iter(gateway.refund_calls.values())) == 1
    events = await service.list_events(started.case_id)
    assert any(event.event_type == "tool_call_retried" for event in events)


async def test_verification_mismatch_routes_to_manual_review():
    service, _, _, started, resumed = await run_approved("verification_mismatch")

    assert resumed.status == "manual_review"
    case = await service.get_case(started.case_id)
    assert case.outcome and case.outcome.failure_code == "refund_verification_mismatch"
    assert case.outcome.terminal_status == "manual_review"


async def test_no_duplicate_finishes_without_approval_or_refund():
    service, _, _ = make_service(NoDuplicateGateway())
    started = await service.start(
        StartCaseRequest(
            complaint="I think I was charged twice for one purchase.",
            customer_id="customer-1",
            scenario_id="no_duplicate",
        )
    )

    assert started.status == "completed"
    assert started.approval_required is False
    case = await service.get_case(started.case_id)
    assert case.outcome and case.outcome.refund_status == "not_requested"


async def test_transient_account_read_has_bounded_visible_retries():
    service, _, gateway = make_service()
    started = await service.start(
        StartCaseRequest(
            complaint="I was charged twice for the same purchase.",
            customer_id="customer-1",
            scenario_id="transient_failure",
        )
    )

    assert started.status == "failed"
    assert gateway.load_calls["transient_failure"] == 2
    retries = [
        event
        for event in await service.list_events(started.case_id)
        if event.event_type == "tool_call_retried"
    ]
    assert len(retries) == 1


async def test_denial_resumes_to_closed_without_refund():
    service, _, gateway = make_service()
    started = await service.start(
        StartCaseRequest(
            complaint="I was charged twice for the same purchase.",
            customer_id="customer-1",
        )
    )
    await service.submit_approval(
        started.case_id,
        ApprovalRequest(
            checkpoint_id=started.checkpoint_id or "",
            decision="deny",
            reviewer_id="reviewer-2",
            reason="Evidence requires offline review",
        ),
    )
    resumed = await service.resume(started.case_id)

    assert resumed.status == "completed"
    case = await service.get_case(started.case_id)
    assert case.outcome and case.outcome.refund_status == "not_requested"
    assert gateway.refunds == {}


@pytest.mark.parametrize(
    ("billing_ok", "decision", "terminal"),
    [
        (True, "ineligible", "completed_no_refund"),
        (False, "ineligible", "failed"),
        (True, None, "failed"),
    ],
)
async def test_policy_no_refund_requires_a_known_decision_and_valid_billing(
    monkeypatch, billing_ok, decision, terminal
):
    gateway = FakeDomainGateway()
    monkeypatch.setattr(
        gateway,
        "validate_billing",
        AsyncMock(
            return_value=ToolResult(
                ok=billing_ok, code=None if billing_ok else "BILLING_VALIDATION_FAILED"
            )
        ),
    )
    monkeypatch.setattr(
        gateway,
        "validate_policy",
        AsyncMock(
            return_value=ToolResult(
                ok=False,
                code="POLICY_INELIGIBLE",
                value={"decision": decision},
                safe_summary="Policy assessment completed.",
            )
        ),
    )
    service, audit, _ = make_service(gateway)
    started = await service.start(
        StartCaseRequest(
            complaint="I was charged twice.",
            customer_id="customer-1",
        )
    )
    case = await service.get_case(started.case_id)
    assert case.outcome and case.outcome.terminal_status == terminal
    assert case.outcome.policy_decision == ("ineligible" if decision else "manual_review")
    assert case.outcome.refund_status == "not_requested"
    assert case.outcome.notification_status == "not_sent"
    assert not started.approval_required
    assert await audit.get_pending_approval(started.run_id) is None
    assert gateway.refunds == {}
    if decision == "ineligible":
        events = await audit.list_events(started.run_id)
        assert not any(
            event.node == "policy_validation" and event.event_type == "tool_call_failed"
            for event in events
        )


@pytest.mark.parametrize("acknowledged", [True, False])
@pytest.mark.parametrize("recovers", [True, False])
async def test_missing_refund_identifier_stays_uncertain_until_resolved(
    monkeypatch, acknowledged, recovers
):
    gateway = FakeDomainGateway()
    submit = gateway.submit_refund
    calls = []

    async def uncertain(run_id, customer_id, evidence, key, scenario_id):
        calls.append(key)
        result = await submit(run_id, customer_id, evidence, key, scenario_id)
        if recovers and len(calls) == 2:
            return result
        return ToolResult(
            ok=acknowledged,
            uncertain=not acknowledged,
            safe_summary="Response omitted the refund identifier.",
        )

    monkeypatch.setattr(gateway, "submit_refund", uncertain)
    service, _, _ = make_service(gateway)
    started = await service.start(
        StartCaseRequest(
            complaint="I was charged twice.",
            customer_id="customer-1",
        )
    )
    await service.submit_approval(
        started.case_id,
        ApprovalRequest(
            checkpoint_id=started.checkpoint_id,
            decision="approve",
            reviewer_id="reviewer-1",
        ),
    )
    resumed = await service.resume(started.case_id)
    assert resumed.status == ("completed" if recovers else "manual_review")
    case = await service.get_case(started.case_id)
    assert case.outcome is not None
    assert case.outcome.refund_status == ("verified" if recovers else "manual_review")
    assert case.outcome.notification_status == ("sent" if recovers else "not_sent")
    assert case.outcome.failure_code == ("none" if recovers else "refund_outcome_uncertain")
    assert len(calls) == 2 and calls[0] == calls[1]
    assert len(gateway.refunds) == 1
    if not recovers:
        events = await service.list_events(started.case_id)
        assert any("reconciliation is required" in event.summary for event in events)
        assert not any(event.node == "notify_customer" for event in events)
