# Shared domain package

Framework-neutral contracts, fixtures, evaluation expectations, and deterministic
simulators for the double-charge scenario.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e "shared[test]"
python -m pytest shared/tests
```

The package intentionally has one runtime dependency: Pydantic v2. It contains no
web, database, cloud, telemetry, model, agent-framework, or workflow-runtime code.
