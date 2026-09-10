import asyncio
import re

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def checkpoint_conninfo(database_url: str, schema: str) -> str:
    """Return a psycopg DSN that resolves unqualified saver tables in one schema."""
    _validate_schema(schema)
    values = conninfo_to_dict(database_url)
    existing_options = values.pop("options", "").strip()
    search_path = f"-csearch_path={schema}"
    options = f"{existing_options} {search_path}".strip()
    return make_conninfo(**values, options=options)


async def ensure_checkpoint_schema(database_url: str, schema: str) -> None:
    """Create the isolated schema before AsyncPostgresSaver runs its migrations."""
    _validate_schema(schema)
    async with await AsyncConnection.connect(database_url, autocommit=True) as connection:
        await connection.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
        )


def _validate_schema(schema: str) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
        raise ValueError("Checkpoint schema must be a lowercase SQL identifier")


async def setup_checkpoints(database_url: str, schema: str, *, require_fresh: bool = False) -> None:
    from .migrations import StorageNotReadyError, require_unused_schemas, validate_schema

    validate_schema(schema)
    async with await AsyncConnection.connect(database_url, autocommit=True) as coordinator:
        # A blocking lock SELECT keeps a snapshot alive and can deadlock the saver's
        # CREATE INDEX CONCURRENTLY. Complete each try-lock transaction before waiting.
        async with asyncio.timeout(60):
            while True:
                result = await coordinator.execute(
                    "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                    (f"langgraph:checkpoint-migrations:{schema}",),
                )
                if (await result.fetchone())[0]:
                    break
                await asyncio.sleep(0.1)
        try:
            if require_fresh:
                await require_unused_schemas(coordinator, [schema])
            await coordinator.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
            )
            # Saver 3.1.2 owns a single autocommit connection, not the audit pool.
            async with AsyncPostgresSaver.from_conn_string(
                checkpoint_conninfo(database_url, schema)
            ) as saver:
                result = await saver.conn.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname=%s", (schema,)
                )
                tables = {row["tablename"] for row in await result.fetchall()}
                if tables and "checkpoint_migrations" not in tables:
                    raise StorageNotReadyError("Unversioned checkpoint schema rejected")
                if "checkpoint_migrations" in tables:
                    result = await saver.conn.execute(
                        "SELECT v FROM checkpoint_migrations ORDER BY v"
                    )
                    history = [row["v"] for row in await result.fetchall()]
                    if history != list(range(len(history))) or len(history) > len(saver.MIGRATIONS):
                        raise StorageNotReadyError(
                            "Native checkpoint migration history is incompatible"
                        )
                await saver.setup()
        finally:
            await coordinator.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                (f"langgraph:checkpoint-migrations:{schema}",),
            )


async def verify_checkpoints(connection: AsyncConnection, schema: str) -> None:
    from .migrations import StorageNotReadyError, validate_schema, verify_unique_keys

    validate_schema(schema)
    result = await connection.execute(
        "SELECT to_regclass(%s) AS relation", (f"{schema}.checkpoint_migrations",)
    )
    if (await result.fetchone())["relation"] is None:
        raise StorageNotReadyError("Native checkpoint schema is missing; run explicit setup")
    result = await connection.execute(
        sql.SQL("SELECT v FROM {}.checkpoint_migrations ORDER BY v").format(sql.Identifier(schema))
    )
    if [row["v"] for row in await result.fetchall()] != list(
        range(len(AsyncPostgresSaver.MIGRATIONS))
    ):
        raise StorageNotReadyError("Native checkpoint migration version is incompatible")
    for table, columns in {
        "checkpoints": "thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, "
        "type, checkpoint, metadata",
        "checkpoint_blobs": "thread_id, checkpoint_ns, channel, version, type, blob",
        "checkpoint_writes": "thread_id, checkpoint_ns, checkpoint_id, task_id, idx, "
        "channel, type, blob, task_path",
    }.items():
        await connection.execute(
            sql.SQL("SELECT {} FROM {}.{} LIMIT 0").format(
                sql.SQL(columns), sql.Identifier(schema), sql.Identifier(table)
            )
        )
    await verify_unique_keys(
        connection,
        schema,
        {
            "checkpoint_migrations": [("v",)],
            "checkpoints": [("thread_id", "checkpoint_ns", "checkpoint_id")],
            "checkpoint_blobs": [("thread_id", "checkpoint_ns", "channel", "version")],
            "checkpoint_writes": [
                ("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx")
            ],
        },
    )
