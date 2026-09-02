from __future__ import annotations

import pytest
from maf_double_charge.model_client import FakeModelClient
from maf_double_charge.models import (
    ApprovalCommand,
    ApprovalDecision,
    RunStatus,
    ScenarioInput,
)
from maf_double_charge.orchestrator import DoubleChargeOrchestrator
from maf_double_charge.repository import InMemoryRepository
from model_to_harness_shared import WorkflowOutcome


def command(fixture_id: str) -> ScenarioInput:
    return ScenarioInput(
        complaint="I was charged twice for the same purchase.",
        customer_id="customer-100",
        scenario_id=fixture_id,
    )


async def approve_and_resume(
    orchestrator: DoubleChargeOrchestrator,
    run_id: str,
    checkpoint_id: str,
    decision: ApprovalDecision = ApprovalDecision.APPROVE,
):
    await orchestrator.record_approval(
        run_id,
        ApprovalCommand(
            checkpoint_id=checkpoint_id,
            decision=decision,
            reviewer_id="test-reviewer",
            reason="Fixture decision",
        ),
    )
    return await orchestrator.resume(run_id, checkpoint_id)


@pytest.mark.parametrize(
    ("fixture_id", "terminal"),
    [
        ("no-duplicate", "completed_no_refund"),
        ("transient-failure", "failed"),
    ],
)
async def test_terminal_routes(
    orchestrator: DoubleChargeOrchestrator, fixture_id: str, terminal: str
) -> None:
    started = await orchestrator.start(command(fixture_id))
    outcome = await orchestrator.get_outcome(started.run_id)
    assert outcome is not None
    assert outcome.terminal_status == terminal


async def test_maf_checkpoint_approval_pause_and_resume(
    orchestrator: DoubleChargeOrchestrator,
    repository: InMemoryRepository,
) -> None:
    started = await orchestrator.start(command("duplicate-confirmed"))
    assert started.status == RunStatus.PAUSED
    assert started.approval_required
    assert started.checkpoint_id
    paused = await repository.get_state(started.run_id)
    assert paused and paused.terminal_status == "waiting_approval"

    completed = await approve_and_resume(
        orchestrator, started.run_id, started.checkpoint_id
    )
    outcome = await orchestrator.get_outcome(started.run_id)
    assert completed.status == RunStatus.COMPLETED
    assert isinstance(outcome, WorkflowOutcome)
    assert outcome.terminal_status == "completed_refunded"
    assert outcome.refund_status == "verified"
    assert outcome.refund_id

    event_types = [
        event.event_type for event in await repository.list_events(started.run_id)
    ]
    assert "checkpoint.created" in event_types
    assert "approval.recorded" in event_types
    assert "workflow.resumed" in event_types
    assert "approval.resolved" in event_types
    assert any(item.startswith("maf.native.") for item in event_types)


async def test_approval_denial_closes_without_refund(
    orchestrator: DoubleChargeOrchestrator,
) -> None:
    started = await orchestrator.start(command("approval-denied"))
    assert started.checkpoint_id
    await approve_and_resume(
        orchestrator,
        started.run_id,
        started.checkpoint_id,
        ApprovalDecision.DENY,
    )
    outcome = await orchestrator.get_outcome(started.run_id)
    assert outcome and outcome.terminal_status == "closed_denied"
    assert outcome.refund_status == "not_requested"


async def test_uncertain_refund_retries_with_one_idempotent_refund(
    orchestrator: DoubleChargeOrchestrator,
    repository: InMemoryRepository,
) -> None:
    started = await orchestrator.start(command("retry-safe-refund"))
    assert started.checkpoint_id
    await approve_and_resume(orchestrator, started.run_id, started.checkpoint_id)
    outcome = await orchestrator.get_outcome(started.run_id)
    events = await repository.list_events(started.run_id)
    assert outcome and outcome.terminal_status == "completed_refunded"
    retries = [
        event
        for event in events
        if event.event_type == "tool.call.retried"
        and event.node == "submit_refund"
    ]
    assert len(retries) == 1
    verification = next(
        event for event in events if event.event_type == "refund.verification"
    )
    assert verification.payload["matching_refund_count"] == 1


async def test_verification_mismatch_routes_to_manual_review(
    orchestrator: DoubleChargeOrchestrator,
) -> None:
    started = await orchestrator.start(command("verification-mismatch"))
    assert started.checkpoint_id
    await approve_and_resume(orchestrator, started.run_id, started.checkpoint_id)
    outcome = await orchestrator.get_outcome(started.run_id)
    assert outcome and outcome.terminal_status == "manual_review"
    assert outcome.failure_code == "refund_verification_mismatch"


async def test_parallel_validation_is_visible_and_joined(
    orchestrator: DoubleChargeOrchestrator,
    repository: InMemoryRepository,
) -> None:
    started = await orchestrator.start(command("duplicate-confirmed"))
    events = await repository.list_events(started.run_id)
    branches = {
        event.node
        for event in events
        if event.event_type == "parallel.branch.completed"
    }
    assert branches == {"billing_validation", "policy_validation"}
    assert any(event.event_type == "parallel.joined" for event in events)


async def test_approval_conflict_is_rejected(
    orchestrator: DoubleChargeOrchestrator,
) -> None:
    started = await orchestrator.start(command("duplicate-confirmed"))
    assert started.checkpoint_id
    first = ApprovalCommand(
        checkpoint_id=started.checkpoint_id,
        decision=ApprovalDecision.APPROVE,
        reviewer_id="reviewer-a",
    )
    await orchestrator.record_approval(started.run_id, first)
    with pytest.raises(ValueError, match="another decision"):
        await orchestrator.record_approval(
            started.run_id,
            first.model_copy(
                update={
                    "decision": ApprovalDecision.DENY,
                    "reviewer_id": "reviewer-b",
                }
            ),
        )


async def test_fake_model_is_used_for_tests(
    orchestrator: DoubleChargeOrchestrator, model: FakeModelClient
) -> None:
    await orchestrator.start(command("no-duplicate"))
    assert model.calls == ["normalize"]

