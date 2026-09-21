from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime

from maf_double_charge.application.errors import StorageReadinessError
from maf_double_charge.config import Settings
from maf_double_charge.infrastructure.persistence.history_maintenance import (
    prune_incompatible_history,
)
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository
from psycopg import Error


async def run(args: argparse.Namespace) -> dict[str, object]:
    settings = Settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is required.")
    if args.apply and args.confirm_schema != settings.database_schema:
        raise ValueError("Apply requires --confirm-schema matching DATABASE_SCHEMA.")
    repository = PostgresRepository(settings.database_url, settings.database_schema)
    try:
        await repository.initialize()
        counts = await prune_incompatible_history(
            repository, before=args.before, apply=args.apply, expected_count=args.confirm_count
        )
        return {"schema": settings.database_schema, "applied": args.apply, "counts": counts}
    finally:
        await repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or remove incompatible MAF case history.")
    parser.add_argument("--before", required=True, type=datetime.fromisoformat)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-schema")
    parser.add_argument("--confirm-count", type=int)
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(run(args))))
    except ValueError as exc:
        parser.error(str(exc))
    except (Error, StorageReadinessError) as exc:
        print(
            f"History cleanup failed ({type(exc).__name__}); no success is claimed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
