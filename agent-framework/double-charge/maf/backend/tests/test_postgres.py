from __future__ import annotations

import os

import pytest
from maf_double_charge.config import Settings
from maf_double_charge.model_client import FakeModelClient
from maf_double_charge.models import (
    ApprovalCommand,
    ApprovalDecision,
    ScenarioInput,
)
from maf_double_charge.orchestrator import DoubleChargeOrchestrator
from maf_double_charge.repository import PostgresRepository
from maf_double_charge.shared_actions import UncertainRefundResponseError
from psycopg import AsyncConnection


async def _drop_test_schema(database_url: str) -> None:
    async with await AsyncConnection.connect(database_url) as conn:
        await conn.execute("DROP SCHEMA IF EXISTS maf_double_charge CASCADE")
        await conn.commit()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to exercise the app-owned PostgreSQL schema.",
)
async def test_uncertain_refund_survives_repository_reconstruction() -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    await _drop_test_schema(database_url)
    settings = Settings(
        database_url=database_url,
        database_schema="maf_double_charge",
        foundry_project_endpoint=None,
        foundry_model=None,
    )
    first_repository = PostgresRepository(database_url, "maf_double_charge")
    second_repository: PostgresRepository | None = None
    try:
        await first_repository.initialize()
        first = DoubleChargeOrchestrator(
            first_repository, FakeModelClient(), settings
        )
        started = await first.start(
            ScenarioInput(
                complaint="I was charged twice.",
                customer_id="customer-100",
                scenario_id="retry-safe-refund",
            )
        )
        assert started.checkpoint_id
        await first.record_approval(
            started.run_id,
            ApprovalCommand(
                checkpoint_id=started.checkpoint_id,
                decision=ApprovalDecision.APPROVE,
                reviewer_id="postgres-test-reviewer",
            ),
        )
        paused = await first.get_state(started.run_id)
        actions = first.actions.get_or_restore(paused.run_id, paused.scenario_id)
        with pytest.raises(UncertainRefundResponseError):
            await first.refunds.submit(paused, actions)
        assert await first_repository.count_refunds(paused.idempotency_key) == 1
        stored_before_restart = await first_repository.get_refund(
            paused.idempotency_key
        )
        assert stored_before_restart is not None
        await first_repository.close()

        second_repository = PostgresRepository(database_url, "maf_double_charge")
        await second_repository.initialize()
        async with second_repository.pool.connection() as conn:
            result = await conn.execute(
                """
                SELECT
                    to_regclass('maf_double_charge.maf_checkpoints')::text
                        AS checkpoint_table,
                    to_regclass('maf_double_charge.refund_ledger')::text
                        AS refund_table
                """
            )
            tables = await result.fetchone()
        assert tables["checkpoint_table"] == "maf_double_charge.maf_checkpoints"
        assert tables["refund_table"] == "maf_double_charge.refund_ledger"

        reconstructed = DoubleChargeOrchestrator(
            second_repository, FakeModelClient(), settings
        )
        terminal = await reconstructed.resume(
            started.run_id, started.checkpoint_id
        )
        outcome = await reconstructed.get_outcome(started.run_id)
        stored_after_restart = await second_repository.get_refund(
            paused.idempotency_key
        )
        assert terminal.terminal_status == "completed_refunded"
        assert terminal.refund_status == "verified"
        assert outcome is not None
        assert outcome.terminal_status == "completed_refunded"
        assert await second_repository.count_refunds(paused.idempotency_key) == 1
        assert stored_after_restart is not None
        assert stored_after_restart.refund_id == stored_before_restart.refund_id
    finally:
        if second_repository is not None:
            await second_repository.close()
        elif not first_repository.pool.closed:
            await first_repository.close()
        await _drop_test_schema(database_url)
