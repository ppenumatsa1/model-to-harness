from __future__ import annotations

import os
import shutil
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from maf_double_charge.infrastructure.persistence.migrations import apply_migrations
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository
from psycopg import AsyncConnection, sql


@pytest.fixture
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to the dedicated maf_cutover_tests database.")
    parsed = urlsplit(value)
    if (
        parsed.hostname != "127.0.0.1"
        or parsed.port != 5434
        or parsed.path != "/maf_cutover_tests"
        or parsed.username != "mafdev"
    ):
        pytest.fail("Persistence tests require the dedicated loopback:5434 maf_cutover_tests DB.")
    return value


@pytest.fixture
async def database_schema(database_url: str):
    schema = f"maf_cutover_test_{uuid4().hex}"
    try:
        yield schema
    finally:
        async with await AsyncConnection.connect(database_url) as conn:
            await conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.fixture
def migration_directory():
    root = Path.cwd() / ".test-artifacts"
    directory = root / f"migrations-{uuid4().hex}"
    directory.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "migrations"
    for path in source.glob("*.sql"):
        shutil.copyfile(path, directory / path.name)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)
        with suppress(OSError):
            root.rmdir()


@pytest.fixture
async def postgres_repository(database_url: str, database_schema: str):
    await apply_migrations(database_url, database_schema)
    repository = PostgresRepository(database_url, database_schema)
    await repository.initialize()
    try:
        yield repository
    finally:
        await repository.close()
