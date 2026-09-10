from __future__ import annotations

import pytest
from maf_double_charge.application.commands import ApprovalCommand, ScenarioInput
from maf_double_charge.application.models import ApprovalDecision, RunStatus
from maf_double_charge.application.refunds import DurableRefundService
from maf_double_charge.application.service import DoubleChargeService
from maf_double_charge.bootstrap import create_runtime
from maf_double_charge.config import Settings
from maf_double_charge.infrastructure.simulated_actions import SimulatedActions
from maf_double_charge.maf.dependencies import WorkflowDependencies
from maf_double_charge.maf.workflows.double_charge import build_workflow
from maf_double_charge.testing.checkpoints import InMemoryRunCheckpointStorage
from maf_double_charge.testing.model import FakeModelClient
from maf_double_charge.testing.repository import InMemoryRepository
from model_to_harness_shared import WorkflowOutcome


def command(fixture_id: str) -> ScenarioInput:
    return ScenarioInput(
        complaint="I was charged twice for the same purchase.",
        customer_id="customer-100",
        scenario_id=fixture_id,
    )


async def approve_and_resume(
    service: DoubleChargeService,
    run_id: str,
    checkpoint_id: str,
    decision: ApprovalDecision = ApprovalDecision.APPROVE,
):
    await service.record_approval(
        run_id,
        ApprovalCommand(
            checkpoint_id=checkpoint_id,
            decision=decision,
            reviewer_id="test-reviewer",
            reason="Fixture decision",
        ),
    )
    return await service.resume(run_id, checkpoint_id)


@pytest.mark.parametrize(
    ("fixture_id", "terminal"),
    [
        ("no-duplicate", "completed_no_refund"),
        ("transient-failure", "failed"),
    ],
)
async def test_terminal_routes(
    service: DoubleChargeService, fixture_id: str, terminal: str
) -> None:
    started = await service.start(command(fixture_id))
    outcome = await service.get_outcome(started.run_id)
    assert outcome is not None
    assert outcome.terminal_status == terminal


async def test_maf_checkpoint_approval_pause_and_resume(
    service: DoubleChargeService,
    repository: InMemoryRepository,
) -> None:
    started = await service.start(command("duplicate-confirmed"))
    assert started.status == RunStatus.PAUSED
    assert started.approval_required
    assert started.checkpoint_id
    paused = await repository.get_state(started.run_id)
    assert paused and paused.terminal_status == "waiting_approval"

    completed = await approve_and_resume(service, started.run_id, started.checkpoint_id)
    outcome = await service.get_outcome(started.run_id)
    assert completed.status == RunStatus.COMPLETED
    assert isinstance(outcome, WorkflowOutcome)
    assert outcome.terminal_status == "completed_refunded"
    assert outcome.refund_status == "verified"
    assert outcome.refund_id

    event_types = [event.event_type for event in await repository.list_events(started.run_id)]
    assert "checkpoint.created" in event_types
    assert "approval.recorded" in event_types
    assert "workflow.resumed" in event_types
    assert "approval.resolved" in event_types
    assert any(item.startswith("maf.native.") for item in event_types)


async def test_approval_denial_closes_without_refund(
    service: DoubleChargeService,
) -> None:
    started = await service.start(command("approval-denied"))
    assert started.checkpoint_id
    await approve_and_resume(
        service,
        started.run_id,
        started.checkpoint_id,
        ApprovalDecision.DENY,
    )
    outcome = await service.get_outcome(started.run_id)
    assert outcome and outcome.terminal_status == "closed_denied"
    assert outcome.refund_status == "not_requested"


async def test_uncertain_refund_retries_with_one_idempotent_refund(
    service: DoubleChargeService,
    repository: InMemoryRepository,
) -> None:
    started = await service.start(command("retry-safe-refund"))
    assert started.checkpoint_id
    await approve_and_resume(service, started.run_id, started.checkpoint_id)
    outcome = await service.get_outcome(started.run_id)
    events = await repository.list_events(started.run_id)
    assert outcome and outcome.terminal_status == "completed_refunded"
    retries = [
        event
        for event in events
        if event.event_type == "tool.call.retried" and event.node == "submit_refund"
    ]
    assert len(retries) == 1
    verification = next(event for event in events if event.event_type == "refund.verification")
    assert verification.payload["matching_refund_count"] == 1


async def test_verification_mismatch_routes_to_manual_review(
    service: DoubleChargeService,
) -> None:
    started = await service.start(command("verification-mismatch"))
    assert started.checkpoint_id
    await approve_and_resume(service, started.run_id, started.checkpoint_id)
    outcome = await service.get_outcome(started.run_id)
    assert outcome and outcome.terminal_status == "manual_review"
    assert outcome.failure_code == "refund_verification_mismatch"


async def test_parallel_validation_is_visible_and_joined(
    service: DoubleChargeService,
    repository: InMemoryRepository,
) -> None:
    started = await service.start(command("duplicate-confirmed"))
    events = await repository.list_events(started.run_id)
    branches = {event.node for event in events if event.event_type == "parallel.branch.completed"}
    assert branches == {"billing_validation", "policy_validation"}
    assert any(event.event_type == "parallel.joined" for event in events)


async def test_approval_conflict_is_rejected(
    service: DoubleChargeService,
) -> None:
    started = await service.start(command("duplicate-confirmed"))
    assert started.checkpoint_id
    first = ApprovalCommand(
        checkpoint_id=started.checkpoint_id,
        decision=ApprovalDecision.APPROVE,
        reviewer_id="reviewer-a",
    )
    await service.record_approval(started.run_id, first)
    with pytest.raises(ValueError, match="another decision"):
        await service.record_approval(
            started.run_id,
            first.model_copy(
                update={
                    "decision": ApprovalDecision.DENY,
                    "reviewer_id": "reviewer-b",
                }
            ),
        )


async def test_fake_model_is_used_for_tests(
    service: DoubleChargeService, model: FakeModelClient
) -> None:
    await service.start(command("no-duplicate"))
    assert model.calls == ["normalize"]


async def test_repeated_identical_approval_preserves_original_decision_timestamp(
    service: DoubleChargeService, repository: InMemoryRepository
) -> None:
    started = await service.start(command("duplicate-confirmed"))
    assert started.checkpoint_id
    approval = ApprovalCommand(
        checkpoint_id=started.checkpoint_id,
        decision=ApprovalDecision.APPROVE,
        reviewer_id="reviewer-a",
        reason="Reviewed evidence",
    )
    await service.record_approval(started.run_id, approval)
    original = await repository.get_approval(started.run_id)
    await service.record_approval(started.run_id, approval)
    assert await repository.get_approval(started.run_id) == original
    assert (
        len(
            [
                event
                for event in await repository.list_events(started.run_id)
                if event.event_type == "approval.recorded"
            ]
        )
        == 1
    )
    assert (await service.get_state(started.run_id)).status == RunStatus.PAUSED


async def test_resume_requires_recorded_approval_and_current_checkpoint(
    service: DoubleChargeService,
) -> None:
    started = await service.start(command("duplicate-confirmed"))
    assert started.checkpoint_id
    with pytest.raises(ValueError, match="checkpoint_id"):
        await service.resume(started.run_id, "stale-checkpoint")
    with pytest.raises(ValueError, match="record an approval"):
        await service.resume(started.run_id, started.checkpoint_id)
    with pytest.raises(ValueError, match="checkpoint_id"):
        await service.record_approval(
            started.run_id,
            ApprovalCommand(
                checkpoint_id="stale-checkpoint",
                decision=ApprovalDecision.APPROVE,
                reviewer_id="reviewer",
            ),
        )


async def test_resume_reconstructs_runtime_without_process_local_actions(
    service: DoubleChargeService, repository: InMemoryRepository, settings: Settings
) -> None:
    started = await service.start(command("duplicate-confirmed"))
    assert started.checkpoint_id
    await service.record_approval(
        started.run_id,
        ApprovalCommand(
            checkpoint_id=started.checkpoint_id,
            decision=ApprovalDecision.APPROVE,
            reviewer_id="restart-reviewer",
        ),
    )
    runtime = create_runtime(
        settings,
        repository=repository,
        model=FakeModelClient(),
        checkpoint_storage_factory=InMemoryRunCheckpointStorage,
    )
    await runtime.start()
    try:
        completed = await runtime.service.resume(started.run_id, started.checkpoint_id)
        assert completed.refund_status == "verified"
        assert completed.notification_status == "sent"
        assert await repository.count_refunds(completed.idempotency_key) == 1
        with pytest.raises(ValueError, match="not paused"):
            await runtime.service.resume(started.run_id, started.checkpoint_id)
    finally:
        await runtime.close()


def test_native_graph_preserves_executor_ids_and_framework_fan_in(
    repository: InMemoryRepository,
    model: FakeModelClient,
) -> None:
    workflow = build_workflow(
        WorkflowDependencies(
            repository,
            model,
            SimulatedActions.for_fixture("duplicate-confirmed"),
            DurableRefundService(repository),
            3,
        ),
        "native-graph-test",
    )
    assert workflow.start_executor_id == "normalize_complaint"
    assert set(workflow.executors) == {
        "normalize_complaint",
        "load_account",
        "detect_duplicate",
        "prepare_validation",
        "billing_validation",
        "policy_validation",
        "join_validations",
        "approval_checkpoint",
        "submit_refund",
        "verify_refund",
        "notify_customer",
        "close_case",
        "close_no_duplicate",
        "close_denied",
        "route_failure",
        "manual_review",
    }
    fan_in = [group for group in workflow.edge_groups if group.type == "FanInEdgeGroup"]
    assert len(fan_in) == 1
    assert {(edge.source_id, edge.target_id) for edge in fan_in[0].edges} == {
        ("billing_validation", "join_validations"),
        ("policy_validation", "join_validations"),
    }


async def test_single_allowed_refund_attempt_never_notifies_on_uncertain_response(
    repository: InMemoryRepository,
    settings: Settings,
) -> None:
    runtime = create_runtime(
        settings.model_copy(update={"max_tool_attempts": 1}),
        repository=repository,
        model=FakeModelClient(),
        checkpoint_storage_factory=InMemoryRunCheckpointStorage,
    )
    await runtime.start()
    try:
        started = await runtime.service.start(command("retry-safe-refund"))
        assert started.checkpoint_id
        completed = await approve_and_resume(runtime.service, started.run_id, started.checkpoint_id)
        assert completed.status == RunStatus.FAILED
        assert completed.failure_code == "refund_submission_failed"
        assert completed.notification_status == "not_sent"
        assert await repository.count_refunds(completed.idempotency_key) == 1
    finally:
        await runtime.close()
