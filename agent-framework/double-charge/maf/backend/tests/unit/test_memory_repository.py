from __future__ import annotations

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
from maf_double_charge.testing.repository import InMemoryRepository


def _state(suffix: str) -> WorkflowState:
    return WorkflowState(
        case_id=f"case-{suffix}",
        run_id=f"run-{suffix}",
        complaint="I was charged twice.",
        customer_id="customer-100",
        scenario_id="duplicate-confirmed",
        idempotency_key=f"key-{suffix}",
    )


async def test_memory_approval_retry_preserves_first_timestamp_and_conflicts() -> None:
    repository = InMemoryRepository()
    await repository.initialize()
    await repository.check_ready()
    state = _state("approval")
    await repository.create_run(state)
    response = ApprovalResponse(decision=ApprovalDecision.APPROVE, reviewer_id="reviewer")
    await repository.save_approval(state.run_id, "checkpoint", response)
    await repository.save_approval(
        state.run_id,
        "checkpoint",
        response.model_copy(update={"decided_at": response.decided_at + timedelta(seconds=1)}),
    )
    assert await repository.get_approval(state.run_id) == response
    for update in (
        {"decision": ApprovalDecision.DENY},
        {"reviewer_id": "different"},
        {"reason": "different"},
    ):
        with pytest.raises(ValueError, match="another decision"):
            await repository.save_approval(
                state.run_id, "checkpoint", response.model_copy(update=update)
            )
    with pytest.raises(ValueError, match="another decision"):
        await repository.save_approval(state.run_id, "other-checkpoint", response)
    await repository.close()


async def test_memory_records_are_isolated_and_event_sequence_matches_postgres() -> None:
    repository = InMemoryRepository()
    first_state, second_state = _state("first"), _state("second")
    await repository.create_run(first_state)
    await repository.create_run(second_state)
    with pytest.raises(ValueError, match="already exists"):
        await repository.create_run(first_state)
    first = await repository.append_event(
        DurableEvent(
            case_id=first_state.case_id,
            run_id=first_state.run_id,
            event_type="run.started",
            summary="Started.",
            payload={"safe": True},
        )
    )
    second = await repository.append_event(
        DurableEvent(
            case_id=second_state.case_id,
            run_id=second_state.run_id,
            event_type="run.started",
            summary="Started.",
        )
    )
    assert second.sequence > first.sequence
    first.payload.clear()
    assert (await repository.list_events(first_state.run_id))[0].payload == {"safe": True}
    assert await repository.list_events(first_state.run_id, after=first.sequence) == []
    restored = await repository.get_state(first_state.run_id)
    restored.account_summary["changed"] = True
    assert not (await repository.get_state_by_case(first_state.case_id)).account_summary
    await repository.set_checkpoint(first_state.run_id, "checkpoint")
    assert (await repository.get_state(first_state.run_id)).checkpoint_id == "checkpoint"


async def test_memory_refund_idempotency_conflict_and_readonly_count() -> None:
    repository = InMemoryRepository()
    state = _state("refund")
    await repository.create_run(state)
    entry = RefundLedgerEntry(
        idempotency_key=state.idempotency_key,
        request_fingerprint="fingerprint",
        account_id="account",
        charge_id="charge",
        amount=Decimal("49.99"),
        currency="USD",
        refund_id="refund",
        refund={"status": "succeeded"},
        created_by_run_id=state.run_id,
    )
    assert await repository.store_refund(entry) == (entry, True)
    assert await repository.store_refund(entry) == (entry, False)
    assert await repository.count_refunds(state.idempotency_key) == 1
    assert await repository.count_refunds(state.idempotency_key) == 1
    assert await repository.get_refund(state.idempotency_key) == entry
    with pytest.raises(RefundIdempotencyConflictError):
        await repository.store_refund(entry.model_copy(update={"request_fingerprint": "changed"}))
