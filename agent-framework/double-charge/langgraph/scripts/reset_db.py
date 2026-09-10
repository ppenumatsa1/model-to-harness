"""Retired: application-only resets can orphan durable native checkpoints."""


def main() -> None:
    raise SystemExit(
        "Database reset is disabled. Select new, distinct LANGGRAPH_SCHEMA and "
        "LANGGRAPH_CHECKPOINT_SCHEMA values, then run scripts/setup_db.py to start fresh. "
        "Existing application records and native checkpoints are left untouched."
    )


if __name__ == "__main__":
    main()
