# Project structure

```text
copilot-sdk/
  backend/src/checkout_recovery_copilot/
    api/                  FastAPI factory, authentication, contracts and routes
    application/          Explicit commands, service, models and ports
    sdk/                  Native Copilot investigator, tools and session integration
    infrastructure/       PostgreSQL, test repository and telemetry
    projections/          Safe transformations of loaded records
    bootstrap.py          Owned runtime resources
    config.py             Lane-local settings
  backend/migrations/     Explicit lane-owned schema changes
  backend/tests/          Contracts, durability, lifecycle and native integration
  frontend/               Independent React workspace and browser tests
  infra/                  Application IaC and generated Hosted package
  scripts/                Development, packaging, release and acceptance commands
  evals/                  Seven-scenario evaluation contract
  observability/          Trace acceptance queries
  docs/design/            Lane design and actual issue/release ledger
```

Generated Hosted application copies are not another editable implementation.
Private `.env`, `.env.compose`, `.azure/`, `.acceptance/` and native session state
must not enter source control or deployment archives.

The root `shared/` package is the only permitted common code: neutral models,
fixtures, simulators and evaluation contracts. Other lane source is a comparison
reference, not a runtime dependency.
