from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from maf_double_charge.application.errors import SchemaVersionError
from maf_double_charge.infrastructure.persistence import migrations as migration_module
from maf_double_charge.infrastructure.persistence.migrations import (
    MigrationChecksumError,
    MigrationError,
    MigrationHistoryError,
    UnversionedSchemaError,
    apply_migrations,
    check_schema,
    load_migrations,
    main,
)
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row


async def _schema_exists(database_url: str, schema: str) -> bool:
    async with await AsyncConnection.connect(database_url) as conn:
        result = await conn.execute(
            "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s", (schema,)
        )
        return await result.fetchone() is not None


def test_default_lookup_prefers_bundled_sql(
    migration_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = migration_directory / "package"
    bundled = package / "_migrations"
    bundled.mkdir(parents=True)
    (bundled / "007_packaged.sql").write_text("SELECT 7;")
    monkeypatch.setattr(migration_module, "files", lambda package_name: package)
    assert [migration.name for migration in load_migrations()] == ["007_packaged.sql"]


async def test_verified_editable_fallback_supports_default_runtime_lookup(
    database_url: str,
    database_schema: str,
    migration_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        migration_module, "files", lambda package_name: migration_directory / "no-bundled-package"
    )
    assert load_migrations() == load_migrations(migration_directory)
    assert await apply_migrations(database_url, database_schema) == [1]
    repository = PostgresRepository(database_url, database_schema)
    await repository.initialize()
    try:
        await repository.check_ready()
    finally:
        await repository.close()


def test_missing_installed_resources_never_use_an_unrelated_parent_directory(
    migration_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = migration_directory / "lib"
    package = installed / "site-packages" / "maf_double_charge"
    unrelated = installed / "migrations"
    unrelated.mkdir(parents=True)
    (unrelated / "001_unrelated.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migration_module, "files", lambda package_name: package)
    monkeypatch.setattr(
        migration_module,
        "__file__",
        str(package / "infrastructure" / "persistence" / "migrations.py"),
    )
    with pytest.raises(MigrationError, match="Migration resources are missing"):
        load_migrations()


async def test_fresh_repeat_and_readonly_runtime(database_url: str, database_schema: str) -> None:
    repository = PostgresRepository(database_url, database_schema)
    with pytest.raises(SchemaVersionError, match="maf-double-charge-migrate"):
        await repository.initialize()
    assert repository.pool.closed
    assert not await _schema_exists(database_url, database_schema)
    assert await apply_migrations(database_url, database_schema) == [1]
    assert await apply_migrations(database_url, database_schema) == []
    repository = PostgresRepository(database_url, database_schema)
    await repository.initialize()
    try:
        await repository.check_ready()
        async with repository.pool.connection() as conn:
            result = await conn.execute("SELECT version, name, checksum FROM schema_migrations")
            assert await result.fetchone() == {
                "version": 1,
                "name": "001_maf_double_charge.sql",
                "checksum": load_migrations()[0].checksum,
            }
            await conn.execute("DELETE FROM schema_migrations")
        with pytest.raises(SchemaVersionError, match="incompatible"):
            await repository.check_ready()
    finally:
        await repository.close()


async def test_changed_checksum_is_rejected(
    database_url: str, database_schema: str, migration_directory: Path
) -> None:
    await apply_migrations(database_url, database_schema, migrations_dir=migration_directory)
    path = migration_directory / "001_maf_double_charge.sql"
    path.write_text(path.read_text() + "\n-- changed after application\n")
    with pytest.raises(MigrationChecksumError, match="modified checksum"):
        await apply_migrations(database_url, database_schema, migrations_dir=migration_directory)


async def test_inconsistent_history_is_rejected(database_url: str, database_schema: str) -> None:
    await apply_migrations(database_url, database_schema)
    async with await AsyncConnection.connect(database_url) as conn:
        await conn.execute(
            sql.SQL("UPDATE {}.schema_migrations SET version = 2").format(
                sql.Identifier(database_schema)
            )
        )
    with pytest.raises(MigrationHistoryError, match="ordered source prefix"):
        await apply_migrations(database_url, database_schema)
    repository = PostgresRepository(database_url, database_schema)
    with pytest.raises(SchemaVersionError, match="incompatible"):
        await repository.initialize()
    assert repository.pool.closed


async def test_all_pending_migrations_roll_back_on_invalid_sql(
    database_url: str, database_schema: str, migration_directory: Path
) -> None:
    (migration_directory / "002_broken.sql").write_text(
        "CREATE TABLE should_rollback (id integer); THIS IS INVALID SQL;"
    )
    with pytest.raises(MigrationError, match="002_broken.sql failed"):
        await apply_migrations(database_url, database_schema, migrations_dir=migration_directory)
    assert not await _schema_exists(database_url, database_schema)
    (migration_directory / "002_broken.sql").unlink()
    assert await apply_migrations(
        database_url, database_schema, migrations_dir=migration_directory
    ) == [1]


async def test_failed_upgrade_preserves_applied_history(
    database_url: str, database_schema: str, migration_directory: Path
) -> None:
    await apply_migrations(database_url, database_schema, migrations_dir=migration_directory)
    (migration_directory / "002_broken.sql").write_text(
        "CREATE TABLE should_rollback (id integer); SELECT missing_column;"
    )
    with pytest.raises(MigrationError):
        await apply_migrations(database_url, database_schema, migrations_dir=migration_directory)
    async with await AsyncConnection.connect(database_url, row_factory=dict_row) as conn:
        result = await conn.execute(
            sql.SQL("SELECT version FROM {}.schema_migrations").format(
                sql.Identifier(database_schema)
            )
        )
        assert await result.fetchall() == [{"version": 1}]
        result = await conn.execute(
            """
            SELECT 1 FROM pg_catalog.pg_tables
            WHERE schemaname = %s AND tablename = 'should_rollback'
            """,
            (database_schema,),
        )
        assert await result.fetchone() is None


async def test_concurrent_migrators_serialize(database_url: str, database_schema: str) -> None:
    results = await asyncio.gather(
        *(apply_migrations(database_url, database_schema) for _ in range(4))
    )
    assert sorted(results) == [[], [], [], [1]]


async def test_existing_empty_schema_and_sorted_pending_versions(
    database_url: str, database_schema: str, migration_directory: Path
) -> None:
    async with await AsyncConnection.connect(database_url) as conn:
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(database_schema)))
    assert await apply_migrations(
        database_url, database_schema, migrations_dir=migration_directory
    ) == [1]
    (migration_directory / "10_last.sql").write_text(
        "INSERT INTO migration_order (version) VALUES (10);"
    )
    (migration_directory / "2_next.sql").write_text(
        "CREATE TABLE migration_order (version integer); "
        "INSERT INTO migration_order (version) VALUES (2);"
    )
    async with await AsyncConnection.connect(database_url, row_factory=dict_row) as conn:
        with pytest.raises(SchemaVersionError, match="pending migrations"):
            await check_schema(conn, database_schema, migrations_dir=migration_directory)
    assert await apply_migrations(
        database_url, database_schema, migrations_dir=migration_directory
    ) == [2, 10]
    async with await AsyncConnection.connect(database_url, row_factory=dict_row) as conn:
        await check_schema(conn, database_schema, migrations_dir=migration_directory)
        result = await conn.execute(
            sql.SQL("SELECT version FROM {}.migration_order ORDER BY version").format(
                sql.Identifier(database_schema)
            )
        )
        assert await result.fetchall() == [{"version": 2}, {"version": 10}]
    assert (
        await apply_migrations(database_url, database_schema, migrations_dir=migration_directory)
        == []
    )


async def test_empty_ledger_cannot_baseline_an_unversioned_schema(
    database_url: str, database_schema: str
) -> None:
    await apply_migrations(database_url, database_schema)
    async with await AsyncConnection.connect(database_url) as conn:
        await conn.execute(
            sql.SQL("DELETE FROM {}.schema_migrations").format(sql.Identifier(database_schema))
        )
    with pytest.raises(MigrationHistoryError, match="no baseline adoption"):
        await apply_migrations(database_url, database_schema)


@pytest.mark.parametrize("create_empty_schema", [False, True])
async def test_fresh_release_requirement_rejects_any_existing_installation(
    database_url: str, database_schema: str, create_empty_schema: bool
) -> None:
    if create_empty_schema:
        async with await AsyncConnection.connect(database_url) as conn:
            await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(database_schema)))
    assert await apply_migrations(database_url, database_schema, require_empty=True) == [1]
    with pytest.raises(MigrationHistoryError, match="requires an absent or empty"):
        await apply_migrations(database_url, database_schema, require_empty=True)
    assert await apply_migrations(database_url, database_schema) == []


async def test_concurrent_fresh_releases_cannot_both_adopt_the_same_schema(
    database_url: str, database_schema: str
) -> None:
    results = await asyncio.gather(
        *(apply_migrations(database_url, database_schema, require_empty=True) for _ in range(2)),
        return_exceptions=True,
    )
    assert results.count([1]) == 1
    assert sum(isinstance(result, MigrationHistoryError) for result in results) == 1


def test_canonical_migration_cli(
    database_url: str,
    database_schema: str,
    migration_directory: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "DATABASE_SCHEMA": database_schema,
    }
    command = [
        sys.executable,
        "-m",
        "maf_double_charge.infrastructure.persistence.migrations",
        "--migrations-dir",
        str(migration_directory),
    ]
    first = subprocess.run(
        [*command, "--require-empty"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    second = subprocess.run(command, env=environment, capture_output=True, text=True, check=True)
    rejected = subprocess.run(
        [*command, "--require-empty"], env=environment, capture_output=True, text=True
    )
    assert "Applied migration versions: [1]" in first.stdout
    assert "already current" in second.stdout
    assert database_url not in first.stdout + first.stderr + second.stdout + second.stderr
    assert rejected.returncode == 1
    assert "requires an absent or empty" in rejected.stderr
    assert database_url not in rejected.stderr
    main(
        [
            "--database-url",
            database_url,
            "--schema",
            database_schema,
            "--migrations-dir",
            str(migration_directory),
        ]
    )
    assert "already current" in capsys.readouterr().out


@pytest.mark.parametrize(
    "legacy_object",
    [
        "CREATE TABLE {}.runs (run_id text)",
        "CREATE TYPE {}.old_state AS ENUM ('paused')",
        "CREATE FUNCTION {}.legacy() RETURNS integer LANGUAGE sql AS 'SELECT 1'",
    ],
)
async def test_nonempty_unversioned_schema_is_never_adopted(
    database_url: str, database_schema: str, legacy_object: str
) -> None:
    async with await AsyncConnection.connect(database_url) as conn:
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(database_schema)))
        await conn.execute(sql.SQL(legacy_object).format(sql.Identifier(database_schema)))
    with pytest.raises(UnversionedSchemaError, match="fresh empty"):
        await apply_migrations(database_url, database_schema)
    async with await AsyncConnection.connect(database_url) as conn:
        result = await conn.execute(
            """
            SELECT 1 FROM pg_catalog.pg_tables
            WHERE schemaname = %s AND tablename = 'schema_migrations'
            """,
            (database_schema,),
        )
        assert await result.fetchone() is None


async def test_quoted_schema_is_treated_as_one_identifier(database_url: str) -> None:
    schema = f'maf_cutover_test_{uuid4().hex}"; --'
    try:
        assert await apply_migrations(database_url, schema) == [1]
        repository = PostgresRepository(database_url, schema)
        await repository.initialize()
        await repository.close()
        assert await _schema_exists(database_url, schema)
    finally:
        async with await AsyncConnection.connect(database_url) as conn:
            await conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )
