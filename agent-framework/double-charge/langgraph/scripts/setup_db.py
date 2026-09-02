"""Create LangGraph-owned audit and checkpoint schemas with Psycopg."""

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from model_to_harness_langgraph.audit import PostgresAuditRepository
from model_to_harness_langgraph.checkpointing import (
    checkpoint_conninfo,
    ensure_checkpoint_schema,
)
from model_to_harness_langgraph.config import get_settings


async def main() -> None:
    settings = get_settings()
    audit = PostgresAuditRepository(settings.database_url, settings.langgraph_schema)
    try:
        await audit.setup()
    finally:
        await audit.close()
    await ensure_checkpoint_schema(
        settings.database_url,
        settings.langgraph_checkpoint_schema,
    )
    async with AsyncPostgresSaver.from_conn_string(
        checkpoint_conninfo(
            settings.database_url,
            settings.langgraph_checkpoint_schema,
        )
    ) as saver:
        await saver.setup()
    print(
        f"{settings.langgraph_schema} audit tables and "
        f"{settings.langgraph_checkpoint_schema} checkpoint tables are ready."
    )


if __name__ == "__main__":
    asyncio.run(main())

