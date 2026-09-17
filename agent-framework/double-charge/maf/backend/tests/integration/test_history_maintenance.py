from datetime import UTC, datetime

import pytest
from maf_double_charge.application.audit import Audit
from maf_double_charge.application.commands import ApprovalCommand, ScenarioInput
from maf_double_charge.application.service import DoubleChargeService
from maf_double_charge.infrastructure.persistence.history_maintenance import (
    prune_incompatible_history,
)
from maf_double_charge.infrastructure.persistence.maf_checkpoints import (
    PostgresRunCheckpointStorage,
)
from maf_double_charge.infrastructure.simulated_actions import SimulatedActions
from maf_double_charge.maf.runner import MafWorkflowRunner
from maf_double_charge.testing.model import FakeModelClient


@pytest.fixture
async def persistent_service(postgres_repository):
    model = FakeModelClient()
    try:
        yield DoubleChargeService(postgres_repository, MafWorkflowRunner(
            postgres_repository, model,
            checkpoint_storage_factory=PostgresRunCheckpointStorage,
            actions_factory=SimulatedActions.for_fixture, max_tool_attempts=3,
        ), model)
    finally:
        await model.close()


async def seed(service, case_id, *, complete=False):
    started = await service.start(ScenarioInput(
        operator_id="opener", customer_id="customer", complaint="Two charges for one purchase.",
        existing_case_id=case_id, idempotency_key=case_id,
    ))
    if complete:
        await service.record_approval(started.run_id, ApprovalCommand(
            checkpoint_id=started.checkpoint_id, decision="approve",
            reviewer_id="reviewer", reason="Reviewed duplicate evidence.",
        ))
        await service.resume(started.run_id, started.checkpoint_id, operator_id="resumer")
    return await service.get_state(started.run_id)


async def make_incompatible(repository, run_id):
    async with repository.pool.connection() as conn:
        await conn.execute(
            """UPDATE execution_events SET payload = payload - 'audit_version'
            WHERE run_id = %s AND event_type = 'run.started'""", (run_id,)
        )


async def test_pruning_only_removes_incompatible_cases_and_their_owned_records(persistent_service):
    service = persistent_service
    repository = service.repository
    old = await seed(service, "old-case", complete=True)
    kept = await seed(service, "kept-case")
    await make_incompatible(repository, old.run_id)
    before = datetime.now(UTC)
    newer = await seed(service, "newer-case")
    await make_incompatible(repository, newer.run_id)
    kept_events = await repository.list_events(kept.run_id)
    preview = await prune_incompatible_history(repository, before=before)
    assert preview["runs"] == 1 and preview["refund_ledger"] == 1
    assert preview["approvals"] == preview["outcomes"] == preview["selected_memory"] == 1
    assert preview["maf_checkpoints"] > 0 and preview["execution_events"] > 0
    assert await repository.get_state(old.run_id)
    with pytest.raises(ValueError, match="Candidate count changed"):
        await prune_incompatible_history(repository, before=before, apply=True, expected_count=2)
    assert await repository.get_state(old.run_id)
    result = await prune_incompatible_history(
        repository, before=before, apply=True, expected_count=1
    )
    assert result == preview
    assert await repository.get_state(old.run_id) is None
    assert not await repository.list_events(old.run_id)
    assert await repository.get_outcome(old.run_id) is None
    assert await repository.get_approval(old.run_id) is None
    assert not await repository.get_memory(old.case_id)
    assert await repository.get_refund(old.idempotency_key) is None
    assert await repository.get_state(kept.run_id) == kept
    assert await repository.list_events(kept.run_id) == kept_events
    assert await repository.get_state(newer.run_id) == newer
    storage = PostgresRunCheckpointStorage(repository, kept.run_id)
    checkpoint = await storage.load(kept.checkpoint_id)
    assert checkpoint.checkpoint_id == kept.checkpoint_id
    assert (await prune_incompatible_history(repository, before=before))["runs"] == 0


async def test_cleanup_refuses_refunds_used_by_retained_cases(persistent_service):
    service = persistent_service
    repository = service.repository
    old = await seed(service, "old-refund", complete=True)
    alias = old.model_copy(update={"run_id": "retained-run", "case_id": "retained-case"})
    await repository.create_run(alias)
    await Audit(repository).emit(alias, "run.started", "Case opened.", actor_id="operator")
    await make_incompatible(repository, old.run_id)
    before = datetime.now(UTC)
    preview = await prune_incompatible_history(repository, before=before)
    assert preview["runs"] == 1 and preview["shared_refunds"] == 1
    with pytest.raises(ValueError, match="Retained cases reference"):
        await prune_incompatible_history(repository, before=before, apply=True, expected_count=1)
    assert await repository.get_refund(old.idempotency_key)
    assert await repository.get_state(old.run_id) == old


async def test_cleanup_refuses_running_cases_and_recognizes_incompatible_later_events(
    persistent_service,
):
    from maf_double_charge.application.models import RunStatus

    service = persistent_service
    repository = service.repository
    state = await seed(service, "incompatible-later")
    async with repository.pool.connection() as conn:
        await conn.execute(
            """UPDATE execution_events SET payload = payload - 'actor_id'
            WHERE run_id = %s AND event_type = 'approval.requested'""", (state.run_id,)
        )
    await repository.save_state(state.model_copy(update={"status": RunStatus.RUNNING}))
    before = datetime.now(UTC)
    preview = await prune_incompatible_history(repository, before=before)
    assert preview["runs"] == preview["running_cases"] == 1
    with pytest.raises(ValueError, match="running cases"):
        await prune_incompatible_history(repository, before=before, apply=True, expected_count=1)
    assert await repository.get_state(state.run_id)
    with pytest.raises(ValueError, match="timezone"):
        await prune_incompatible_history(repository, before=before.replace(tzinfo=None))
    with pytest.raises(ValueError, match="expected case count"):
        await prune_incompatible_history(repository, before=before, apply=True)
