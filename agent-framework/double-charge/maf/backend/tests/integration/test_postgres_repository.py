from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from maf_double_charge.application.errors import RefundIdempotencyConflictError
from maf_double_charge.application.models import (
    ApprovalDecision,
    ApprovalResponse,
    DurableEvent,
    RefundLedgerEntry,
    WorkflowState,
)
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository


def _state(suffix: str = "postgres") -> WorkflowState:
    return WorkflowState(
        run_id=f"run-{suffix}",
        case_id=f"case-{suffix}",
        complaint="I was charged twice.",
        customer_id="customer-100",
        scenario_id="duplicate-confirmed",
        idempotency_key=f"refund-{suffix}",
    )


async def test_durable_records_survive_repository_restart(
    postgres_repository: PostgresRepository, database_url: str, database_schema: str
) -> None:
    state = _state()
    await postgres_repository.create_run(state)
    state = state.advance("load_account")
    await postgres_repository.save_state(state)
    await postgres_repository.save_memory(state.case_id, {"summary": "duplicate evidence"})
    first = await postgres_repository.append_event(
        DurableEvent(
            case_id=state.case_id,
            run_id=state.run_id,
            event_type="node.started",
            summary="Loading account.",
            node="load_account",
        )
    )
    second = await postgres_repository.append_event(
        DurableEvent(
            case_id=state.case_id,
            run_id=state.run_id,
            event_type="node.completed",
            summary="Account loaded.",
            node="load_account",
        )
    )
    await postgres_repository.set_checkpoint(state.run_id, "checkpoint-new")
    await postgres_repository.close()
    restarted = PostgresRepository(database_url, database_schema)
    await restarted.initialize()
    try:
        stored = await restarted.get_state_by_case(state.case_id)
        assert stored.current_step == "load_account"
        assert stored.checkpoint_id == "checkpoint-new"
        assert await restarted.get_state(state.run_id) == stored
        assert await restarted.get_memory(state.case_id) == {"summary": "duplicate evidence"}
        assert await restarted.list_events(state.run_id) == [first, second]
        assert await restarted.list_events(state.run_id, after=first.sequence) == [second]
        assert second.sequence > first.sequence
        assert await restarted.get_state("missing") is None
        assert await restarted.get_memory("missing") == {}
    finally:
        await restarted.close()


async def test_approval_retry_compares_stable_intent_and_preserves_original_time(
    postgres_repository: PostgresRepository,
) -> None:
    state = _state()
    await postgres_repository.create_run(state)
    approval = ApprovalResponse(
        decision=ApprovalDecision.APPROVE,
        reviewer_id="reviewer",
        reason="confirmed",
    )
    retry = approval.model_copy(update={"decided_at": approval.decided_at + timedelta(seconds=1)})
    await asyncio.gather(
        postgres_repository.save_approval(state.run_id, "checkpoint", approval),
        postgres_repository.save_approval(state.run_id, "checkpoint", retry),
    )
    stored = await postgres_repository.get_approval(state.run_id)
    assert stored in (approval, retry)
    await postgres_repository.save_approval(state.run_id, "checkpoint", retry)
    assert await postgres_repository.get_approval(state.run_id) == stored
    for update in (
        {"decision": ApprovalDecision.DENY},
        {"reviewer_id": "different"},
        {"reason": "changed"},
    ):
        with pytest.raises(ValueError, match="another decision"):
            await postgres_repository.save_approval(
                state.run_id, "checkpoint", approval.model_copy(update=update)
            )
    with pytest.raises(ValueError, match="another decision"):
        await postgres_repository.save_approval(state.run_id, "other-checkpoint", approval)


async def test_refund_idempotency_is_durable_and_counting_is_readonly(
    postgres_repository: PostgresRepository, database_url: str, database_schema: str
) -> None:
    state = _state()
    await postgres_repository.create_run(state)
    entry = RefundLedgerEntry(
        idempotency_key=state.idempotency_key,
        request_fingerprint="same-request",
        account_id="account-100",
        charge_id="charge-duplicate",
        amount=Decimal("49.99"),
        currency="USD",
        refund_id="refund-100",
        refund={"status": "succeeded"},
        created_by_run_id=state.run_id,
    )
    results = await asyncio.gather(*(postgres_repository.store_refund(entry) for _ in range(4)))
    assert sum(created for _, created in results) == 1
    assert all(stored == entry for stored, _ in results)
    before = await postgres_repository.get_refund(state.idempotency_key)
    assert await postgres_repository.count_refunds(state.idempotency_key) == 1
    assert await postgres_repository.count_refunds(state.idempotency_key) == 1
    assert await postgres_repository.get_refund(state.idempotency_key) == before
    with pytest.raises(RefundIdempotencyConflictError, match="different refund request"):
        await postgres_repository.store_refund(
            entry.model_copy(update={"request_fingerprint": "different-request"})
        )
    await postgres_repository.close()
    restarted = PostgresRepository(database_url, database_schema)
    await restarted.initialize()
    try:
        stored, created = await restarted.store_refund(entry)
        assert not created
        assert stored == entry
        assert await restarted.count_refunds(entry.idempotency_key) == 1
    finally:
        await restarted.close()
