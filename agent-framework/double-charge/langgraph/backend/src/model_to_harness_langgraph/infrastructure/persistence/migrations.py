"""Explicit storage setup; application SQL and native saver DDL have separate owners."""

import argparse
import asyncio
import hashlib
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from ...config import Settings
from .checkpointing import setup_checkpoints, verify_checkpoints


class StorageNotReadyError(RuntimeError):
    pass


def validate_schema(schema: str) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
        raise ValueError("Storage schema must be a lowercase SQL identifier of at most 63 bytes")
    if schema in {"public", "langgraph_app", "langgraph_checkpoints"}:
        raise ValueError("Select fresh cutover schemas; legacy storage is not supported")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    statement: str


def load_migrations() -> tuple[Migration, ...]:
    resource = files("model_to_harness_langgraph").joinpath("infrastructure/persistence/sql")
    location = Path(__file__).resolve()
    if resource.is_dir():
        directory = resource
    elif location.parents[3].name == "src" and location.parents[4].name == "backend":
        directory = location.parents[4] / "migrations"
    else:
        raise StorageNotReadyError("Packaged application migration SQL is missing")
    migrations = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        match = re.fullmatch(r"(\d+)_([a-z0-9_]+)\.sql", path.name)
        if path.name.endswith(".sql") and match is None:
            raise StorageNotReadyError("Application migration filename is invalid")
        if match:
            content = path.read_bytes()
            migrations.append(
                Migration(
                    int(match[1]),
                    path.name,
                    hashlib.sha256(content).hexdigest(),
                    content.decode("utf-8"),
                )
            )
    if not migrations or [m.version for m in migrations] != list(range(1, len(migrations) + 1)):
        raise StorageNotReadyError("Application migration resources are missing or unordered")
    return tuple(migrations)


async def _history(connection: AsyncConnection, schema: str) -> list[dict]:
    result = await connection.execute(
        "SELECT to_regclass(%s) AS relation", (f"{schema}.schema_migrations",)
    )
    if (await result.fetchone())["relation"] is None:
        raise StorageNotReadyError("Application migration history is missing; run explicit setup")
    result = await connection.execute(
        sql.SQL("SELECT version, name, checksum FROM {}.schema_migrations ORDER BY version").format(
            sql.Identifier(schema)
        )
    )
    return await result.fetchall()


def _check_history(history: list[dict], migrations: tuple[Migration, ...], *, complete: bool):
    expected = [{"version": m.version, "name": m.name, "checksum": m.checksum} for m in migrations]
    if history != expected[: len(history)] or len(history) > len(expected):
        raise StorageNotReadyError("Application migration history or checksum is incompatible")
    if complete and history != expected:
        raise StorageNotReadyError("Application migrations are pending; run explicit setup")


async def verify_application(connection: AsyncConnection, schema: str) -> None:
    validate_schema(schema)
    _check_history(await _history(connection, schema), load_migrations(), complete=True)
    columns = {
        "runs": "run_id, case_id, customer_id, status, current_step, checkpoint_id, "
        "approval_required, state, outcome, created_at, updated_at",
        "events": "sequence, event_id, case_id, run_id, event_type, event_time, node, "
        "status, summary, data, dedupe_key",
        "approvals": "run_id, checkpoint_id, decision, reviewer_id, reason, consumed",
        "selected_memory": "customer_id, case_id, facts, updated_at",
        "refunds": "idempotency_key, request_fingerprint, refund_id, case_id, run_id, customer_id",
    }
    for table, fields in columns.items():
        await connection.execute(
            sql.SQL("SELECT {} FROM {}.{} LIMIT 0").format(
                sql.SQL(fields), sql.Identifier(schema), sql.Identifier(table)
            )
        )
    await verify_unique_keys(
        connection,
        schema,
        {
            "schema_migrations": [("version",)],
            "runs": [("run_id",), ("case_id",)],
            "events": [("sequence",), ("event_id",), ("run_id", "dedupe_key")],
            "approvals": [("run_id",)],
            "selected_memory": [("customer_id", "case_id")],
            "refunds": [("idempotency_key",), ("refund_id",)],
        },
    )


async def verify_unique_keys(
    connection: AsyncConnection,
    schema: str,
    expected: dict[str, list[tuple[str, ...]]],
) -> None:
    result = await connection.execute(
        """SELECT t.relname AS table_name,
                      ARRAY(SELECT a.attname::text
                            FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, position)
                            JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.attnum
                            ORDER BY k.position) AS columns
               FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
               JOIN pg_namespace n ON n.oid=t.relnamespace
               JOIN pg_index i ON i.indexrelid=c.conindid
               WHERE n.nspname=%s AND c.contype IN ('p','u')
                 AND c.convalidated AND i.indisvalid AND i.indisready""",
        (schema,),
    )
    actual = {(row["table_name"], tuple(row["columns"])) for row in await result.fetchall()}
    required = {(table, key) for table, keys in expected.items() for key in keys}
    if not required <= actual:
        raise StorageNotReadyError("Storage uniqueness constraints are missing or invalid")


async def apply_application(database_url: str, schema: str, *, require_fresh: bool = False) -> None:
    validate_schema(schema)
    migrations = load_migrations()
    async with await AsyncConnection.connect(database_url, row_factory=dict_row) as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"langgraph:application-migrations:{schema}",),
            )
            if require_fresh:
                await require_unused_schemas(connection, [schema])
            existing = await connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)
            )
            tables = {row["tablename"] for row in await existing.fetchall()}
            if tables and "schema_migrations" not in tables:
                raise StorageNotReadyError("Unversioned schema rejected; select fresh storage")
            await connection.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
            )
            await connection.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {}.schema_migrations ("
                    "version integer PRIMARY KEY, name text NOT NULL, checksum text NOT NULL, "
                    "applied_at timestamptz NOT NULL DEFAULT now())"
                ).format(sql.Identifier(schema))
            )
            history = await _history(connection, schema)
            _check_history(history, migrations, complete=False)
            for migration in migrations[len(history) :]:
                await connection.execute(
                    sql.SQL(
                        migration.statement.replace(
                            "__schema__", sql.Identifier(schema).as_string(connection)
                        )
                    )
                )
                await connection.execute(
                    sql.SQL(
                        "INSERT INTO {}.schema_migrations (version,name,checksum) VALUES (%s,%s,%s)"
                    ).format(sql.Identifier(schema)),
                    (migration.version, migration.name, migration.checksum),
                )
            await verify_application(connection, schema)


async def require_unused_schemas(connection: AsyncConnection, schemas: list[str]) -> None:
    result = await connection.execute(
        "SELECT 1 FROM pg_namespace WHERE nspname = ANY(%s) LIMIT 1", (schemas,)
    )
    if await result.fetchone() is not None:
        raise StorageNotReadyError("Fresh setup requires unused application and checkpoint schemas")


async def setup_storage(
    settings: Settings, *, verify_only: bool = False, require_fresh: bool = False
) -> None:
    if verify_only and require_fresh:
        raise ValueError("verify_only and require_fresh are mutually exclusive")
    validate_schema(settings.langgraph_schema)
    validate_schema(settings.langgraph_checkpoint_schema)
    if settings.langgraph_schema == settings.langgraph_checkpoint_schema:
        raise ValueError("Application and checkpoint schemas must be distinct")
    if require_fresh:
        async with await AsyncConnection.connect(settings.database_url) as connection:
            await connection.execute("SET TRANSACTION READ ONLY")
            await require_unused_schemas(
                connection, [settings.langgraph_schema, settings.langgraph_checkpoint_schema]
            )
    if not verify_only:
        await apply_application(
            settings.database_url, settings.langgraph_schema, require_fresh=require_fresh
        )
        await setup_checkpoints(
            settings.database_url, settings.langgraph_checkpoint_schema, require_fresh=require_fresh
        )
    async with await AsyncConnection.connect(
        settings.database_url, row_factory=dict_row
    ) as connection:
        await connection.execute("SET TRANSACTION READ ONLY")
        await verify_application(connection, settings.langgraph_schema)
        await verify_checkpoints(connection, settings.langgraph_checkpoint_schema)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--require-fresh", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        setup_storage(Settings(), verify_only=args.verify_only, require_fresh=args.require_fresh)
    )
    print("LangGraph application and native checkpoint schemas verified.")


if __name__ == "__main__":
    main()
