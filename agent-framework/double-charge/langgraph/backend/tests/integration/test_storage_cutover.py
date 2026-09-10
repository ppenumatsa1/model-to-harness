import asyncio
import os
from dataclasses import replace
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from model_to_harness_langgraph.application.ports import CommandInProgressError
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.infrastructure.persistence import migrations
from model_to_harness_langgraph.infrastructure.persistence.audit import PostgresAuditRepository
from model_to_harness_langgraph.infrastructure.persistence.checkpointing import (
    checkpoint_conninfo,
    verify_checkpoints,
)
from psycopg import AsyncConnection, Error, sql
from psycopg.rows import dict_row

DATABASE = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE, reason="TEST_DATABASE_URL is required")


@pytest.fixture
async def settings():
    suffix = uuid4().hex[:12]
    selected = Settings(
        _env_file=None,
        database_url=DATABASE,
        langgraph_schema=f"lg_app_{suffix}",
        langgraph_checkpoint_schema=f"lg_cp_{suffix}",
    )
    try:
        yield selected
    finally:
        async with await AsyncConnection.connect(DATABASE, autocommit=True) as connection:
            for schema in (selected.langgraph_schema, selected.langgraph_checkpoint_schema):
                await connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )


async def test_fresh_setup_repeat_verify_read_only_and_native_connection_contract(settings):
    with pytest.raises(migrations.StorageNotReadyError, match="missing"):
        await migrations.setup_storage(settings, verify_only=True)
    await migrations.setup_storage(settings)
    await migrations.setup_storage(settings)
    await migrations.setup_storage(settings, verify_only=True)
    async with await AsyncConnection.connect(DATABASE, row_factory=dict_row) as connection:
        await connection.execute("SET TRANSACTION READ ONLY")
        await migrations.verify_application(connection, settings.langgraph_schema)
        await verify_checkpoints(connection, settings.langgraph_checkpoint_schema)
        result = await connection.execute(
            "SELECT count(*) AS count FROM pg_tables WHERE schemaname='public' "
            "AND tablename IN ('checkpoints','checkpoint_writes','checkpoint_blobs')"
        )
        assert (await result.fetchone())["count"] == 0
    async with AsyncPostgresSaver.from_conn_string(
        checkpoint_conninfo(DATABASE, settings.langgraph_checkpoint_schema)
    ) as saver:
        assert isinstance(saver.conn, AsyncConnection)
        assert saver.conn.autocommit is True and saver.conn.prepare_threshold == 0
        connection = saver.conn
    assert connection.closed


async def test_checksum_drift_and_missing_checkpoint_table_fail_readiness(settings):
    await migrations.setup_storage(settings)
    async with await AsyncConnection.connect(DATABASE, autocommit=True) as connection:
        await connection.execute(
            sql.SQL("UPDATE {}.schema_migrations SET checksum='tampered' WHERE version=1").format(
                sql.Identifier(settings.langgraph_schema)
            )
        )
    with pytest.raises(migrations.StorageNotReadyError, match="checksum"):
        await migrations.setup_storage(settings, verify_only=True)
    with pytest.raises(migrations.StorageNotReadyError, match="checksum"):
        await migrations.setup_storage(settings)
    async with await AsyncConnection.connect(
        DATABASE, autocommit=True, row_factory=dict_row
    ) as conn:
        await conn.execute(
            sql.SQL("DROP TABLE {}.checkpoint_writes").format(
                sql.Identifier(settings.langgraph_checkpoint_schema)
            )
        )
        with pytest.raises(Error):
            await verify_checkpoints(conn, settings.langgraph_checkpoint_schema)


async def test_failed_application_migration_rolls_back_schema_and_history(settings, monkeypatch):
    original = migrations.load_migrations()
    broken = replace(
        original[0],
        statement=original[0].statement + "\nSELECT deliberately_missing_function();",
    )
    monkeypatch.setattr(migrations, "load_migrations", lambda: (broken,))
    with pytest.raises(Error):
        await migrations.apply_application(DATABASE, settings.langgraph_schema)
    async with await AsyncConnection.connect(DATABASE) as conn:
        result = await conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname=%s", (settings.langgraph_schema,)
        )
        assert await result.fetchone() is None
    monkeypatch.setattr(migrations, "load_migrations", lambda: original)
    await migrations.setup_storage(settings)


async def test_unversioned_schema_rejected_without_reading_or_changing_its_records(settings):
    async with await AsyncConnection.connect(DATABASE, autocommit=True) as conn:
        await conn.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(settings.langgraph_schema))
        )
        await conn.execute(
            sql.SQL("CREATE TABLE {}.old_data (value text)").format(
                sql.Identifier(settings.langgraph_schema)
            )
        )
        await conn.execute(
            sql.SQL("INSERT INTO {}.old_data VALUES ('untouched')").format(
                sql.Identifier(settings.langgraph_schema)
            )
        )
    with pytest.raises(migrations.StorageNotReadyError, match="Unversioned"):
        await migrations.apply_application(DATABASE, settings.langgraph_schema)
    async with await AsyncConnection.connect(DATABASE) as conn:
        result = await conn.execute(
            sql.SQL("SELECT value FROM {}.old_data").format(
                sql.Identifier(settings.langgraph_schema)
            )
        )
        assert await result.fetchall() == [("untouched",)]


async def test_concurrent_application_setup_serializes_and_command_lock_crosses_repositories(
    settings,
):
    await asyncio.gather(*[migrations.setup_storage(settings) for _ in range(3)])
    first = PostgresAuditRepository(DATABASE, settings.langgraph_schema)
    second = PostgresAuditRepository(DATABASE, settings.langgraph_schema)
    try:
        await first.open()
        await second.open()
        async with first.command_lock("same-case"):
            with pytest.raises(CommandInProgressError):
                async with second.command_lock("same-case"):
                    pytest.fail("Cross-process lock was not enforced")
        async with second.command_lock("same-case"):
            pass
    finally:
        await first.close()
        await second.close()


async def test_command_guards_cannot_starve_the_audit_pool(settings):
    await migrations.setup_storage(settings)
    audit = PostgresAuditRepository(DATABASE, settings.langgraph_schema)
    ready = asyncio.Event()
    entered = 0

    async def worker(index):
        nonlocal entered
        async with audit.command_lock(f"parallel-case-{index}"):
            entered += 1
            if entered == 9:
                ready.set()
            await ready.wait()
            assert await audit.ping()

    try:
        await audit.open()
        await asyncio.wait_for(asyncio.gather(*[worker(i) for i in range(9)]), 10)
        with pytest.raises(RuntimeError):
            async with audit.command_lock("failed-command"):
                raise RuntimeError("worker interrupted")
        async with audit.command_lock("failed-command"):
            pass
    finally:
        await audit.close()


async def test_readiness_rejects_removed_refund_uniqueness(settings):
    await migrations.setup_storage(settings)
    async with await AsyncConnection.connect(DATABASE, autocommit=True) as conn:
        await conn.execute(
            sql.SQL("ALTER TABLE {}.refunds DROP CONSTRAINT refunds_refund_id_key").format(
                sql.Identifier(settings.langgraph_schema)
            )
        )
    with pytest.raises(migrations.StorageNotReadyError, match="uniqueness"):
        await migrations.setup_storage(settings, verify_only=True)


async def test_require_fresh_sets_up_both_schemas_and_rejects_reuse(settings):
    await migrations.setup_storage(settings, require_fresh=True)
    with pytest.raises(migrations.StorageNotReadyError, match="unused"):
        await migrations.setup_storage(settings, require_fresh=True)
    await migrations.setup_storage(settings, verify_only=True)


@pytest.mark.parametrize("existing_store", ["application", "checkpoint"])
async def test_require_fresh_rejects_either_existing_schema_before_any_setup(
    settings, existing_store
):
    existing = (
        settings.langgraph_schema
        if existing_store == "application"
        else settings.langgraph_checkpoint_schema
    )
    untouched = (
        settings.langgraph_checkpoint_schema
        if existing_store == "application"
        else settings.langgraph_schema
    )
    async with await AsyncConnection.connect(DATABASE, autocommit=True) as conn:
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(existing)))
    with pytest.raises(migrations.StorageNotReadyError, match="unused"):
        await migrations.setup_storage(settings, require_fresh=True)
    async with await AsyncConnection.connect(DATABASE) as conn:
        result = await conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (untouched,))
        assert await result.fetchone() is None
        result = await conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=%s", (existing,)
        )
        assert await result.fetchall() == []


async def test_owner_locks_also_enforce_freshness(settings):
    from model_to_harness_langgraph.infrastructure.persistence.checkpointing import (
        setup_checkpoints,
    )

    await migrations.setup_storage(settings, require_fresh=True)
    with pytest.raises(migrations.StorageNotReadyError, match="unused"):
        await migrations.apply_application(DATABASE, settings.langgraph_schema, require_fresh=True)
    with pytest.raises(migrations.StorageNotReadyError, match="unused"):
        await setup_checkpoints(DATABASE, settings.langgraph_checkpoint_schema, require_fresh=True)


@pytest.mark.parametrize(
    "name", ["public", "langgraph_app", "langgraph_checkpoints", "x;DROP", "a" * 64]
)
async def test_invalid_or_legacy_schema_names_rejected_before_connect(name):
    with pytest.raises(ValueError):
        await migrations.apply_application("must-not-connect", name)
