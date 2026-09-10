from __future__ import annotations

import pytest
from maf_double_charge.application.commands import ApprovalCommand, ScenarioInput
from maf_double_charge.application.errors import UncertainRefundResponseError
from maf_double_charge.application.models import ApprovalDecision, RunStatus
from maf_double_charge.application.refunds import DurableRefundService
from maf_double_charge.application.service import DoubleChargeService
from maf_double_charge.infrastructure.persistence.maf_checkpoints import (
    PostgresRunCheckpointStorage,
)
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository
from maf_double_charge.infrastructure.simulated_actions import SimulatedActions
from maf_double_charge.maf.runner import MafWorkflowRunner
from maf_double_charge.testing.model import FakeModelClient


async def test_uncertain_refund_recovers_from_fresh_native_checkpoint_and_repository(
    postgres_repository: PostgresRepository, database_url: str, database_schema: str
) -> None:
    actions = SimulatedActions.for_fixture("retry-safe-refund")
    first_model = FakeModelClient()
    runner = MafWorkflowRunner(
        postgres_repository,
        first_model,
        checkpoint_storage_factory=PostgresRunCheckpointStorage,
        actions_factory=lambda scenario_id: actions,
        max_tool_attempts=3,
    )
    service = DoubleChargeService(postgres_repository, runner)
    started = await service.start(
        ScenarioInput(
            complaint="I was charged twice.",
            customer_id="customer-100",
            scenario_id="retry-safe-refund",
        )
    )
    assert started.status == RunStatus.PAUSED
    assert started.checkpoint_id
    approval = ApprovalCommand(
        checkpoint_id=started.checkpoint_id,
        decision=ApprovalDecision.APPROVE,
        reviewer_id="postgres-workflow-reviewer",
    )
    await service.record_approval(started.run_id, approval)
    original_approval = await postgres_repository.get_approval(started.run_id)
    await service.record_approval(started.run_id, approval)
    assert await postgres_repository.get_approval(started.run_id) == original_approval
    paused = await service.get_state(started.run_id)
    with pytest.raises(UncertainRefundResponseError):
        await DurableRefundService(postgres_repository).submit(paused, actions)
    before = await postgres_repository.get_refund(paused.idempotency_key)
    assert before is not None
    assert await postgres_repository.count_refunds(paused.idempotency_key) == 1
    await first_model.close()
    await postgres_repository.close()

    restarted = PostgresRepository(database_url, database_schema)
    second_model = FakeModelClient()
    await restarted.initialize()
    try:
        reconstructed = DoubleChargeService(
            restarted,
            MafWorkflowRunner(
                restarted,
                second_model,
                checkpoint_storage_factory=PostgresRunCheckpointStorage,
                actions_factory=SimulatedActions.for_fixture,
                max_tool_attempts=3,
            ),
        )
        terminal = await reconstructed.resume(started.run_id, started.checkpoint_id)
        outcome = await reconstructed.get_outcome(started.run_id)
        after = await restarted.get_refund(paused.idempotency_key)
        assert terminal.terminal_status == "completed_refunded"
        assert terminal.refund_status == "verified"
        assert outcome is not None
        assert outcome.terminal_status == "completed_refunded"
        assert await restarted.count_refunds(paused.idempotency_key) == 1
        assert after == before
        events = await restarted.list_events(started.run_id)
        assert sum(event.event_type == "approval.recorded" for event in events) == 1
        assert any(event.event_type == "workflow.resumed" for event in events)
    finally:
        await second_model.close()
        await restarted.close()
