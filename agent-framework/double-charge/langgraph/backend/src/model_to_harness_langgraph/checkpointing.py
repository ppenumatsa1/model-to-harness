import re

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
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        raise ValueError("Checkpoint schema must be a lowercase SQL identifier")
