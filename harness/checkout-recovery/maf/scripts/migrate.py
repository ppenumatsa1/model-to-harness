"""Apply versioned migrations explicitly; startup never mutates the schema."""

import argparse
import hashlib
import os
from pathlib import Path

import psycopg


def migrate(database_url: str, *, apply: bool) -> None:
    paths = sorted((Path(__file__).resolve().parents[1] / "backend/migrations").glob("*.sql"))
    with psycopg.connect(database_url) as connection:
        if apply:
            connection.execute("SELECT pg_advisory_xact_lock(8472001)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS checkout_recovery_schema_migrations (
                   migration_id TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                   applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
        for path in paths:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            row = connection.execute(
                "SELECT checksum FROM checkout_recovery_schema_migrations WHERE migration_id = %s",
                (path.name,),
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise RuntimeError(f"migration checksum mismatch: {path.name}")
            elif apply:
                connection.execute(path.read_text())
                connection.execute(
                    "INSERT INTO checkout_recovery_schema_migrations VALUES (%s, %s, now())",
                    (path.name, digest),
                )
            else:
                raise RuntimeError(f"migration missing: {path.name}")
            print(f"Migration verified: {path.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    migrate(os.environ["CHECKOUT_RECOVERY_DATABASE_URL"], apply=args.apply)
