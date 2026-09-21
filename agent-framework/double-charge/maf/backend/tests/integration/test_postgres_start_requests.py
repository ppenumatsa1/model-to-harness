from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from maf_double_charge.application.errors import (
    SchemaVersionError,
    StartRequestConflictError,
    StartRequestInProgressError,
)
from maf_double_charge.application.models import StartResult, WorkflowState
from maf_double_charge.infrastructure.persistence.migrations import apply_migrations
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository


def state() -> WorkflowState:
    return WorkflowState(
        case_id=f"case-{uuid4()}",
        run_id=f"run-{uuid4()}",
        complaint="Simulated checkout-independent duplicate complaint.",
        customer_id="customer-100",
        scenario_id="no-duplicate",
        idempotency_key=str(uuid4()),
    )


async def test_concurrent_repositories_claim_once_and_recover_after_reconnect(
    postgres_repository, database_url, database_schema
):
    first = postgres_repository
    second = PostgresRepository(database_url, database_schema)
    await second.initialize()
    request_id = str(uuid4())
    try:
        results = await asyncio.gather(
            first.claim_start(request_id, "a" * 64, state()),
            second.claim_start(request_id, "a" * 64, state()),
            return_exceptions=True,
        )
        assert results.count(None) == 1
        pending = next(
            result for result in results if isinstance(result, StartRequestInProgressError)
        )
        async with first.pool.connection() as conn:
            cursor = await conn.execute("SELECT count(*) AS count FROM runs")
            assert (await cursor.fetchone())["count"] == 1
        with pytest.raises(StartRequestConflictError):
            await second.claim_start(request_id, "b" * 64, state())
        receipt = StartResult(
            case_id=pending.case_id,
            run_id=pending.run_id,
            status="paused",
            current_step="approval_checkpoint",
            approval_required=True,
            checkpoint_id="checkpoint",
        )
        await first.complete_start(request_id, receipt)
        with pytest.raises(StartRequestConflictError):
            await first.complete_start(request_id, receipt)
    finally:
        await second.close()
    rebuilt = PostgresRepository(database_url, database_schema)
    await rebuilt.initialize()
    try:
        assert await rebuilt.claim_start(request_id, "a" * 64, state()) == receipt
    finally:
        await rebuilt.close()


async def test_additive_upgrade_preserves_v1_runs_and_history(
    database_url, database_schema, migration_directory: Path
):
    migration = migration_directory / "002_start_requests.sql"
    content = migration.read_text()
    migration.unlink()
    assert await apply_migrations(
        database_url, database_schema, migrations_dir=migration_directory
    ) == [1]
    repository = PostgresRepository(database_url, database_schema)
    await repository.pool.open(wait=True)
    original = state()
    try:
        await repository.create_run(original)
        async with repository.pool.connection() as conn:
            cursor = await conn.execute("SELECT version, checksum FROM schema_migrations")
            history = await cursor.fetchall()
        with pytest.raises(SchemaVersionError, match="pending migrations"):
            await repository.check_ready()
        migration.write_text(content)
        assert await apply_migrations(database_url, database_schema) == [2]
        await repository.check_ready()
        assert await repository.get_state(original.run_id) == original
        async with repository.pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT version, checksum FROM schema_migrations WHERE version=1"
            )
            assert await cursor.fetchall() == history
    finally:
        await repository.close()
