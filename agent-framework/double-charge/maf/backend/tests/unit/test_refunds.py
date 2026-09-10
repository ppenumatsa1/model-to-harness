from __future__ import annotations

from decimal import Decimal

import pytest
from maf_double_charge.application.commands import ScenarioInput
from maf_double_charge.application.errors import (
    RefundIdempotencyConflictError,
    UncertainRefundResponseError,
)
from maf_double_charge.application.models import RefundLedgerEntry
from maf_double_charge.application.refunds import DurableRefundService
from maf_double_charge.application.service import DoubleChargeService
from maf_double_charge.infrastructure.simulated_actions import SimulatedActions
from maf_double_charge.testing.repository import InMemoryRepository
from model_to_harness_shared import DuplicateEvidence


async def test_uncertain_refund_is_recovered_from_durable_ledger(
    service: DoubleChargeService,
    repository: InMemoryRepository,
) -> None:
    started = await service.start(
        ScenarioInput(
            complaint="I was charged twice.",
            customer_id="customer-100",
            scenario_id="retry-safe-refund",
        )
    )
    state = await service.get_state(started.run_id)
    actions = SimulatedActions.for_fixture(state.scenario_id)
    actions.last_evidence = DuplicateEvidence.model_validate(state.duplicate_evidence)
    refunds = DurableRefundService(repository)

    with pytest.raises(UncertainRefundResponseError):
        await refunds.submit(state, actions)

    assert await repository.count_refunds(state.idempotency_key) == 1
    reconstructed_actions = SimulatedActions.for_fixture(state.scenario_id)
    reconstructed_actions.last_evidence = DuplicateEvidence.model_validate(state.duplicate_evidence)
    recovered = await refunds.submit(state, reconstructed_actions)
    assert recovered.recovered_existing is True
    assert recovered.refund["refund_id"]
    assert await repository.count_refunds(state.idempotency_key) == 1
    assert not reconstructed_actions.billing.refunds


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
