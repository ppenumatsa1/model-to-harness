"""Set up paired storage: --require-fresh rejects existing schemas; --verify-only never runs DDL."""

from model_to_harness_langgraph.infrastructure.persistence.migrations import main

if __name__ == "__main__":
    main()
