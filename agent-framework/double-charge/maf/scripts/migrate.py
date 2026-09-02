from __future__ import annotations

import asyncio

from maf_double_charge.config import get_settings
from maf_double_charge.repository import PostgresRepository


async def main() -> None:
    settings = get_settings()
    repository = PostgresRepository(settings.database_url, settings.database_schema)
    await repository.initialize()
    await repository.close()
    print(f"Initialized PostgreSQL schema: {settings.database_schema}")


if __name__ == "__main__":
    asyncio.run(main())

