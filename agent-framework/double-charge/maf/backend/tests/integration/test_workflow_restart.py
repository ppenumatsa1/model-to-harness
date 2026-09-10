from __future__ import annotations

import pytest
from maf_double_charge.application.commands import ApprovalCommand, ScenarioInput
from maf_double_charge.application.errors import UncertainRefundResponseError
from maf_double_charge.application.models import ApprovalDecision, RunStatus
from maf_double_charge.application.refunds import DurableRefundService
from maf_double_charge.bootstrap import create_runtime
from maf_double_charge.config import Settings
from maf_double_charge.infrastructure.persistence.maf_checkpoints import (
    PostgresRunCheckpointStorage,
)
from maf_double_charge.infrastructure.persistence.migrations import apply_migrations
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository
from maf_double_charge.infrastructure.simulated_actions import SimulatedActions
from maf_double_charge.testing.model import FakeModelClient
from model_to_harness_shared import DuplicateEvidence


@pytest.mark.parametrize(
    ("scenario_id", "crash_after_uncertain_refund"),
    [("duplicate-confirmed", False), ("retry-safe-refund", True)],
)
async def test_native_workflow_resumes_after_postgres_and_runtime_reconstruction(
    database_url: str,
    database_schema: str,
    settings: Settings,
    scenario_id: str,
    crash_after_uncertain_refund: bool,
) -> None:
    await apply_migrations(database_url, database_schema)
    first = create_runtime(
        settings,
        repository=PostgresRepository(database_url, database_schema),
        model=FakeModelClient(),
        checkpoint_storage_factory=PostgresRunCheckpointStorage,
    )
    existing_refund_id = None
    await first.start()
    try:
        started = await first.service.start(
            ScenarioInput(
                complaint="I was charged twice for the same purchase.",
                customer_id="customer-100",
                scenario_id=scenario_id,
            )
        )
        assert started.status == RunStatus.PAUSED
        assert started.checkpoint_id
        approval = ApprovalCommand(
            checkpoint_id=started.checkpoint_id,
            decision=ApprovalDecision.APPROVE,
            reviewer_id="restart-reviewer",
        )
        await first.service.record_approval(started.run_id, approval)
        original_approval = await first.repository.get_approval(started.run_id)
        if crash_after_uncertain_refund:
            state = await first.service.get_state(started.run_id)
            actions = SimulatedActions.for_fixture(scenario_id)
            actions.last_evidence = DuplicateEvidence.model_validate(state.duplicate_evidence)
            # Emulate process loss after the side effect but before its workflow checkpoint.
            with pytest.raises(UncertainRefundResponseError):
                await DurableRefundService(first.repository).submit(state, actions)
            stored = await first.repository.get_refund(state.idempotency_key)
            assert stored is not None
            existing_refund_id = stored.refund_id
            assert await first.repository.count_refunds(state.idempotency_key) == 1
        assert not any(
            event.event_type == "notification.sent"
            for event in await first.repository.list_events(started.run_id)
        )
    finally:
        await first.close()

    restarted = create_runtime(
        settings,
        repository=PostgresRepository(database_url, database_schema),
        model=FakeModelClient(),
        checkpoint_storage_factory=PostgresRunCheckpointStorage,
    )
    await restarted.start()
    try:
        await restarted.service.record_approval(started.run_id, approval)
        assert await restarted.repository.get_approval(started.run_id) == original_approval
        completed = await restarted.service.resume(started.run_id, started.checkpoint_id)
        assert completed.status == RunStatus.COMPLETED
        assert completed.refund_status == "verified"
        assert completed.notification_status == "sent"
        assert await restarted.repository.count_refunds(completed.idempotency_key) == 1
        if existing_refund_id is not None:
            assert completed.refund_id == existing_refund_id
        outcome = await restarted.service.get_outcome(started.run_id)
        assert outcome is not None
        assert outcome.terminal_status == "completed_refunded"
        assert outcome.refund_id == completed.refund_id
        events = await restarted.repository.list_events(started.run_id)
        assert sum(event.event_type == "approval.recorded" for event in events) == 1
        assert sum(event.event_type == "notification.sent" for event in events) == 1
        assert any(event.event_type == "workflow.resumed" for event in events)
        assert any(event.event_type.startswith("maf.native.") for event in events)
    finally:
        await restarted.close()
