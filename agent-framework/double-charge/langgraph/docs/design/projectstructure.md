# LangGraph project structure

All paths below are relative to `agent-framework/double-charge/langgraph/`.
This is an independently owned lane, not a shared application template.

```text
langgraph/
  README.md, AGENTS.md
  .env.example                 canonical safe configuration and placeholders
  .env                         private local configuration; never committed
  compose.yaml                 independent PostgreSQL-only local stack
  .env.compose.example          safe template for opt-in local database settings
  .env.compose                  private local database credentials; ignored
  .azure/                      private deployment state; not runtime dotenv fallback
  pyproject.toml, uv.lock       application dependencies and wheel packaging
  backend/
    migrations/001_langgraph_app.sql
    src/model_to_harness_langgraph/
      config.py, main.py       settings and local host/port entrypoint
      bootstrap.py             owned runtime construction and cleanup
      api/                     app factory, routes and HTTP schemas
      application/             records, service, ports and result reconciliation
      graph/
        state.py               native state and concurrent reducers
        runner.py              native invocation, snapshot and resume
        workflows/double_charge.py
        nodes/                 investigation, validation, approval, refund, completion
      infrastructure/
        domain_gateway.py      narrow neutral-simulator adapter
        model_client.py        model/credential/client boundary
        logging.py, telemetry.py
        persistence/           audit, checkpoints and migration ownership
      projections/             safe workspace/state/outcome/AG-UI and hosted command adapter
      testing/                 explicit fake model/gateway and in-memory audit
    tests/                     unit, contracts, integration, native workflow and E2E factory
  frontend/
    src/App.tsx                three-pane case history, execution and business-audit UI
    src/                       lane-owned history/workspace hooks and safe projections
    src/api.ts, src/agui.ts, src/types.ts
    server-config.ts           allowlisted lane-dotenv server configuration only
    vite.config.ts             dev server/proxy and Vitest
    tests/                     component, stream, configuration and browser tests
    package.json, package-lock.json
  scripts/                     local start, setup, evaluation, packaging and release tools
  evals/, eval.yaml             deterministic local evaluation intent
  observability/               independent KQL acceptance queries and guidance
  infra/                       Bicep, API/frontend images and nginx
    foundry-hosted/agent/       Responses main, pins, hosted eval intent and generated package
  azure.yaml                   independent hosted deployment declaration
  .foundry/                    metadata, datasets, suites, evaluators and private results
  docs/design/                 exactly the seven documents below
```

## Seven independently maintained documents

| Topic | Responsibility |
| --- | --- |
| [prd.md](prd.md) | Current capabilities, safety requirements, audience and limits. |
| [business-rules.md](business-rules.md) | Six demo scenarios, plain-English walkthroughs, approval/resume process and core business rules. |
| [userflow.md](userflow.md) | Three-pane journey, persisted history, native SSE, explicit controls and business audit. |
| [architecture.md](architecture.md) | Logical, process, development, physical and scenario views, including diagrams and storage boundaries. |
| [techstack.md](techstack.md) | Dependency roles, canonical configuration and local execution. |
| [projectstructure.md](projectstructure.md) | This ownership/source map. |
| [issues-changes-fixes.md](issues-changes-fixes.md) | LangGraph-only provenance, incidents and local versus deployed evidence. |

There are no extra deployment-flow, schema-I/O, engineering or shared design
documents. Their applicable content belongs in these seven documents. Root
articles/assets are independent publication material, not the lane's runtime
specification.

## Packaging and storage

`backend/migrations/` is authoritative application SQL. Wheel packaging places
it under `model_to_harness_langgraph/infrastructure/persistence/sql`.
Native saver SQL is owned by `langgraph-checkpoint-postgres`, not copied into
application migrations. Runtime startup verifies the configured schema pair;
`scripts/setup_db.py` is an explicit setup/verification entrypoint.

`scripts/prepare_hosted.py` stages the lane and neutral shared package into the
hosted agent's ignored `_packages/` and writes a content-hash manifest.
Generated code is an artifact, not a source to edit or a path back to the
repository. Installed wheels and generated hosted packages must work without
checkout parent directories or dotenv discovery.

`scripts/reset_db.py` is retired rather than an invitation to delete historical
state. Fresh cutover and update-existing release modes have distinct storage
requirements. No schema migration/reset belongs to this documentation/configuration
change.

## Boundaries and local entrypoints

Only the neutral [shared package](../../../../../shared/) is imported across this
lane boundary. No other framework's API, UI, persistence, telemetry, deployment
assets, private environment, identities or results are reused.

`scripts/dev-backend.sh` resolves its own lane and virtualenv from any CWD;
`main.py` reads `HOST`/`PORT`. Vite selects safe server settings from the same
lane `.env`; no file is searched in the root, sibling lane or frontend CWD.
`scripts/with_local_db.py` explicitly selects the lane's Compose PostgreSQL
for a child process without modifying that `.env`; see
[local PostgreSQL](../../README.md#local-postgresql).
Private environment generation, cloud operations and application restart remain
operator/parent-owned actions, not automatic test behavior.

Component guidance remains in [infra](../../infra/README.md),
[observability](../../observability/README.md) and
[Foundry metadata](../../.foundry/README.md). The [ledger](issues-changes-fixes.md)
is the lane's history; it does not incorporate another lane's validation counts.
