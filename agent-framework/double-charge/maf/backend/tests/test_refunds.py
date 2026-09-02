from __future__ import annotations

from decimal import Decimal

import pytest
from maf_double_charge.config import Settings
from maf_double_charge.model_client import FakeModelClient
from maf_double_charge.models import RefundLedgerEntry, ScenarioInput
from maf_double_charge.orchestrator import DoubleChargeOrchestrator
from maf_double_charge.repository import (
    InMemoryRepository,
    RefundIdempotencyConflictError,
)
from maf_double_charge.shared_actions import (
    RootSharedActions,
    UncertainRefundResponseError,
)
from model_to_harness_shared import DuplicateEvidence


async def test_uncertain_refund_is_recovered_from_durable_ledger() -> None:
    repository = InMemoryRepository()
    orchestrator = DoubleChargeOrchestrator(
        repository,
        FakeModelClient(),
        Settings(foundry_project_endpoint=None, foundry_model=None),
    )
    started = await orchestrator.start(
        ScenarioInput(
            complaint="I was charged twice.",
            customer_id="customer-100",
            scenario_id="retry-safe-refund",
        )
    )
    state = await orchestrator.get_state(started.run_id)
    actions = orchestrator.actions.get_or_restore(state.run_id, state.scenario_id)

    with pytest.raises(UncertainRefundResponseError):
        await orchestrator.refunds.submit(state, actions)

    assert await repository.count_refunds(state.idempotency_key) == 1
    reconstructed_actions = RootSharedActions.for_fixture(state.scenario_id)
    reconstructed_actions.last_evidence = DuplicateEvidence.model_validate(
        state.duplicate_evidence
    )
    recovered = await orchestrator.refunds.submit(state, reconstructed_actions)
    assert recovered.recovered_existing is True
    assert recovered.refund["refund_id"]
    assert await repository.count_refunds(state.idempotency_key) == 1


async def test_in_memory_ledger_detects_idempotency_conflicts() -> None:
    repository = InMemoryRepository()
    original = RefundLedgerEntry(
        idempotency_key="same-key",
        request_fingerprint="fingerprint-a",
        account_id="account-1",
        charge_id="charge-1",
        amount=Decimal("10.00"),
        currency="USD",
        refund_id="refund-1",
        refund={"refund_id": "refund-1"},
        created_by_run_id="run-1",
    )
    await repository.store_refund(original)
    conflict = original.model_copy(
        update={"request_fingerprint": "fingerprint-b", "charge_id": "charge-2"}
    )
    with pytest.raises(RefundIdempotencyConflictError):
        await repository.store_refund(conflict)
