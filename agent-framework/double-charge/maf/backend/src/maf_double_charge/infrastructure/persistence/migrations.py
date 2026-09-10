from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from maf_double_charge.application.errors import SchemaVersionError, StorageReadinessError
from psycopg import AsyncConnection, Error, sql
from psycopg.rows import dict_row

_LEDGER = "schema_migrations"
_VERSIONED_SQL = re.compile(r"^(?P<version>[0-9]+)_[a-zA-Z0-9_]+\.sql$")
_MIGRATE_INSTRUCTION = "Run maf-double-charge-migrate against the configured database and schema."
_MISSING_MIGRATIONS = (
    "Migration resources are missing; install the packaged SQL or use --migrations-dir."
)


class MigrationError(RuntimeError):
    """An explicit migration failed without changing its transaction's schema."""


class MigrationHistoryError(MigrationError):
    pass


class MigrationChecksumError(MigrationHistoryError):
    pass


class UnversionedSchemaError(MigrationHistoryError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    statement: str


def validate_schema(schema: str) -> None:
    if (
        not schema
        or "\0" in schema
        or len(schema.encode("utf-8")) > 63
        or schema.startswith("pg_")
        or schema == "information_schema"
    ):
        raise ValueError("Configure a non-system PostgreSQL schema of at most 63 bytes.")


def _checkout_migrations() -> Path:
    package = Path(__file__).resolve().parents[2]
    backend = package.parent.parent
    manifest = backend.parent / "pyproject.toml"
    if (
        package.name != "maf_double_charge"
        or package.parent.name != "src"
        or backend.name != "backend"
        or not manifest.is_file()
    ):
        raise MigrationError(_MISSING_MIGRATIONS)
    try:
        with manifest.open("rb") as stream:
            project = tomllib.load(stream).get("project", {})
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MigrationError(_MISSING_MIGRATIONS) from exc
    if project.get("name") != "model-to-harness-maf":
        raise MigrationError(_MISSING_MIGRATIONS)
    return backend / "migrations"


def load_migrations(migrations_dir: Path | None = None) -> tuple[Migration, ...]:
    if migrations_dir is not None:
        directory = Path(migrations_dir)
    else:
        directory = files("maf_double_charge").joinpath("_migrations")
        if not directory.is_dir():
            # Editable installs use the authoritative checkout SQL, not a second copy.
            directory = _checkout_migrations()
    if not directory.is_dir():
        raise MigrationError(_MISSING_MIGRATIONS)
    migrations: list[Migration] = []
    for path in directory.iterdir():
        if not path.name.endswith(".sql"):
            continue
        match = _VERSIONED_SQL.fullmatch(path.name)
        if match is None:
            raise MigrationHistoryError(f"Invalid migration filename: {path.name}")
        content = path.read_bytes()
        migrations.append(
            Migration(
                version=int(match["version"]),
                name=path.name,
                checksum=hashlib.sha256(content).hexdigest(),
                statement=content.decode("utf-8"),
            )
        )
    migrations.sort(key=lambda migration: migration.version)
    versions = [migration.version for migration in migrations]
    if not versions or versions[0] < 1 or len(versions) != len(set(versions)):
        raise MigrationHistoryError("Migrations require unique positive versions and nonempty SQL.")
    if any(not migration.statement.strip() for migration in migrations):
        raise MigrationHistoryError("Migration SQL must not be empty.")
    return tuple(migrations)


def _validate_history(rows: list[dict[str, Any]], migrations: tuple[Migration, ...]) -> None:
    if len(rows) > len(migrations):
        raise MigrationHistoryError("Database migration history is newer than this application.")
    for row, migration in zip(rows, migrations, strict=False):
        if row["version"] != migration.version or row["name"] != migration.name:
            raise MigrationHistoryError(
                "Database migration history is not an ordered source prefix."
            )
        if row["checksum"] != migration.checksum:
            raise MigrationChecksumError(
                f"Applied migration {migration.name} has a modified checksum; restore its SQL."
            )


async def _ledger_exists(conn: AsyncConnection, schema: str) -> bool:
    result = await conn.execute(
        """
        SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND c.relkind = 'r'
        """,
        (schema, _LEDGER),
    )
    return await result.fetchone() is not None


async def _history(conn: AsyncConnection, schema: str) -> list[dict[str, Any]]:
    result = await conn.execute(
        sql.SQL("SELECT version, name, checksum FROM {}.{} ORDER BY version").format(
            sql.Identifier(schema), sql.Identifier(_LEDGER)
        )
    )
    return await result.fetchall()


async def _schema_has_objects(conn: AsyncConnection, schema: str) -> bool:
    result = await conn.execute(
        """
        SELECT 1 FROM pg_catalog.pg_depend d
        JOIN pg_catalog.pg_namespace n ON n.oid = d.refobjid
        WHERE d.refclassid = 'pg_catalog.pg_namespace'::regclass
          AND n.nspname = %s LIMIT 1
        """,
        (schema,),
    )
    return await result.fetchone() is not None


async def check_schema(
    conn: AsyncConnection, schema: str, *, migrations_dir: Path | None = None
) -> None:
    """Read-only runtime gate: never create a schema, ledger, or application table."""
    validate_schema(schema)
    try:
        migrations = load_migrations(migrations_dir)
        ledger_existed = await _ledger_exists(conn, schema)
        if not ledger_existed:
            raise SchemaVersionError(f"MAF schema is not versioned. {_MIGRATE_INSTRUCTION}")
        rows = await _history(conn, schema)
        if ledger_existed and not rows:
            raise MigrationHistoryError(
                "An existing empty migration ledger is not a versioned installation. "
                "Select a fresh empty MAF-only schema; no baseline adoption is supported."
            )
        _validate_history(rows, migrations)
        if len(rows) != len(migrations):
            raise SchemaVersionError(f"MAF schema has pending migrations. {_MIGRATE_INSTRUCTION}")
    except MigrationError as exc:
        raise SchemaVersionError(
            f"MAF schema is incompatible with this application. {_MIGRATE_INSTRUCTION}"
        ) from exc
    except Error as exc:
        raise SchemaVersionError(
            f"MAF schema history cannot be verified. {_MIGRATE_INSTRUCTION}"
        ) from exc


async def apply_migrations(
    database_url: str,
    schema: str,
    *,
    migrations_dir: Path | None = None,
    require_empty: bool = False,
) -> list[int]:
    """Apply all pending SQL atomically under a database/schema-scoped advisory lock."""
    validate_schema(schema)
    migrations = load_migrations(migrations_dir)
    lock_key = int.from_bytes(
        hashlib.sha256(f"maf-double-charge:migrations:{schema}".encode()).digest()[:8],
        byteorder="big",
        signed=True,
    )
    applied: list[int] = []
    try:
        async with await AsyncConnection.connect(database_url, row_factory=dict_row) as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_catalog.pg_advisory_xact_lock(%s)", (lock_key,))
                if require_empty and await _schema_has_objects(conn, schema):
                    raise MigrationHistoryError(
                        "This release requires an absent or empty MAF-only schema; "
                        "the configured schema already contains objects."
                    )
                ledger_existed = await _ledger_exists(conn, schema)
                if not ledger_existed:
                    if await _schema_has_objects(conn, schema):
                        raise UnversionedSchemaError(
                            "Refusing a nonempty unversioned MAF schema. Select a fresh empty "
                            "MAF-only schema, or explicitly reset only verified MAF-owned storage "
                            "after stopping its writers; no adoption or conversion is supported."
                        )
                    await conn.execute(
                        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
                    )
                    await conn.execute(
                        sql.SQL(
                            """
                            CREATE TABLE {}.{} (
                                version bigint PRIMARY KEY,
                                name text UNIQUE NOT NULL,
                                checksum text NOT NULL,
                                applied_at timestamptz NOT NULL DEFAULT now()
                            )
                            """
                        ).format(sql.Identifier(schema), sql.Identifier(_LEDGER))
                    )
                rows = await _history(conn, schema)
                if ledger_existed and not rows:
                    raise MigrationHistoryError(
                        "An existing empty migration ledger is not a versioned installation. "
                        "Select a fresh empty MAF-only schema; no baseline adoption is supported."
                    )
                _validate_history(rows, migrations)
                await conn.execute(
                    sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(
                        sql.Identifier(schema)
                    )
                )
                for migration in migrations[len(rows) :]:
                    try:
                        await conn.execute(migration.statement)
                    except Error as exc:
                        raise MigrationError(
                            f"Migration {migration.name} failed; "
                            "all pending changes were rolled back."
                        ) from exc
                    await conn.execute(
                        sql.SQL(
                            "INSERT INTO {}.{} (version, name, checksum) VALUES (%s, %s, %s)"
                        ).format(sql.Identifier(schema), sql.Identifier(_LEDGER)),
                        (migration.version, migration.name, migration.checksum),
                    )
                    applied.append(migration.version)
    except Error as exc:
        raise MigrationError(
            "Cannot apply MAF migrations; verify database access and migration history."
        ) from exc
    return applied


def main(argv: Sequence[str] | None = None) -> None:
    from maf_double_charge.config import Settings

    parser = argparse.ArgumentParser(description="Apply explicit MAF-owned PostgreSQL migrations.")
    parser.add_argument("--database-url", help="Defaults to the configured DATABASE_URL.")
    parser.add_argument("--schema", help="Defaults to the configured DATABASE_SCHEMA.")
    parser.add_argument("--migrations-dir", type=Path, help="Use SQL from this source directory.")
    parser.add_argument(
        "--require-empty",
        action="store_true",
        help="Require an absent or empty schema for a fresh release; never reset existing data.",
    )
    args = parser.parse_args(argv)
    settings = Settings()
    try:
        applied = asyncio.run(
            apply_migrations(
                args.database_url or settings.database_url,
                args.schema or settings.database_schema,
                migrations_dir=args.migrations_dir,
                require_empty=args.require_empty,
            )
        )
    except (MigrationError, StorageReadinessError, ValueError) as exc:
        parser.exit(1, f"MAF migration failed: {exc}\n")
    print(f"Applied migration versions: {applied}" if applied else "MAF schema is already current.")


if __name__ == "__main__":
    main()
