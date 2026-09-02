"""Reset only application audit data while preserving durable checkpoints."""

import asyncio

from model_to_harness_langgraph.audit import PostgresAuditRepository
from model_to_harness_langgraph.config import get_settings
from psycopg import AsyncConnection, sql


async def main() -> None:
    settings = get_settings()
    repository = PostgresAuditRepository(
        settings.database_url,
        settings.langgraph_schema,
    )
    async with await AsyncConnection.connect(
        settings.database_url,
        autocommit=True,
    ) as connection:
        await connection.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(repository.schema)
            )
        )
    await repository.setup()
    await repository.close()
    print(
        f"{settings.langgraph_schema} reset; "
        f"{settings.langgraph_checkpoint_schema} checkpoints preserved."
    )


if __name__ == "__main__":
    asyncio.run(main())

