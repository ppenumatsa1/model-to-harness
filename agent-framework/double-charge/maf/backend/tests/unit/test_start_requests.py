from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from maf_double_charge.application.commands import ScenarioInput
from maf_double_charge.application.errors import (
    StartRequestConflictError,
    StartRequestInProgressError,
)
from maf_double_charge.application.service import DoubleChargeService


def command(**changes) -> ScenarioInput:
    return ScenarioInput(
        **{
            "request_id": uuid4(),
            "operator_id": "operator",
            "customer_id": "customer-100",
            "complaint": "Charged twice for this purchase.",
            "scenario_id": "no-duplicate",
            **changes,
        }
    )


async def test_matching_start_recovers_original_receipt_without_workflow_replay(
    service, repository
):
    start = command()
    service.runner.start = AsyncMock(wraps=service.runner.start)
    first = await service.start(start)
    events = await service.list_events(first.run_id)
    rebuilt = DoubleChargeService(repository, service.runner, service.model)
    assert await rebuilt.start(start) == first
    assert len(repository.states) == 1
    assert await service.list_events(first.run_id) == events
    service.runner.start.assert_awaited_once()


@pytest.mark.parametrize(
    "field,value",
    [
        ("complaint", "A different complaint."),
        ("customer_id", "another-customer"),
        ("operator_id", "another-operator"),
        ("scenario_id", "duplicate-confirmed"),
        ("idempotency_key", "different-refund"),
        ("existing_case_id", "different-case"),
    ],
)
async def test_reused_start_identity_rejects_changed_intent(service, repository, field, value):
    start = command()
    await service.start(start)
    with pytest.raises(StartRequestConflictError):
        await service.start(start.model_copy(update={field: value}))
    assert len(repository.states) == 1


async def test_concurrent_start_and_interrupted_claim_never_reexecute(service, repository):
    start = command()
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(_state):
        entered.set()
        await release.wait()
        raise RuntimeError("simulated process interruption")

    service.runner.start = AsyncMock(side_effect=held)
    task = asyncio.create_task(service.start(start))
    await entered.wait()
    try:
        with pytest.raises(StartRequestInProgressError) as error:
            await service.start(start)
        assert error.value.run_id in repository.states
    finally:
        release.set()
    with pytest.raises(RuntimeError, match="process interruption"):
        await task
    rebuilt = DoubleChargeService(repository, service.runner, service.model)
    with pytest.raises(StartRequestInProgressError):
        await rebuilt.start(start)
    service.runner.start.assert_awaited_once()
    assert len(repository.states) == 1


async def test_legacy_start_omission_still_creates_new_runs(service, repository):
    start = command(request_id=None)
    first, second = await service.start(start), await service.start(start)
    assert first.run_id != second.run_id
    assert len(repository.states) == 2
    assert not repository.start_requests
