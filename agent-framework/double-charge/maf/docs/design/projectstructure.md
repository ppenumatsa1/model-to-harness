# MAF project structure

All paths below are relative to the MAF lane unless explicitly qualified. This
is an independently maintained application, not a template for another runtime.

```text
maf/
  README.md                         lane entrypoint, local commands, navigation
  AGENTS.md                         lane boundaries and validation guidance
  pyproject.toml, uv.lock            Python package and locked dependencies
  .env.example                      safe documented configuration template
  .env                              private local values, ignored, operator-owned
  compose.yaml                      independent PostgreSQL-only local stack
  .env.compose.example              safe template for opt-in local database settings
  .env.compose                      private local database credentials, ignored
  .azure/                           private azd/release state, ignored
  backend/
    src/maf_double_charge/
      api/                          app factory, HTTP contracts, routers, dependencies
      application/                  commands/queries, state, ports, service, refunds, audit, history
      maf/                          agents/prompts, clients, executors, workflow, runner
      infrastructure/               PostgreSQL, checkpoints, migrations, simulation, telemetry
      projections/                  pure loaded-data workspace, AG-UI, selected-run facts, graph
      testing/                      explicitly injected model/repository/checkpoint doubles
      config.py                     lane dotenv selection and Settings
      bootstrap.py                  runtime construction and resource lifecycle
      main.py                       canonical API executable
      evaluation.py                 deterministic fake-backed evaluation
    migrations/                     authoritative versioned SQL
    tests/
      unit/                         config, workflow, refund, codec, telemetry, stream tests
      contracts/                    API, workspace, audit, packaging, release, evaluation
      integration/                  disposable PostgreSQL, restart, ordering and history
  frontend/
    src/                            MAF workspace, timeline, audit and assistant
    src/test/                       safe fixtures and test setup
    tests/                          browser, mocked workspace and server-config checks
    devSettings.ts                  exact dotenv -> safe server port/proxy projection
    vite.config.ts                  lane-root dev config, no client dotenv loading
    package.json, package-lock.json  frontend manifest and lock
  scripts/                          lane startup, maintenance, release and acceptance tools
  eval.yaml, evals/run.py            local evaluation intent and runner
  observability/                    setup, KQL acceptance gates and SQL queries
  infra/                            Bicep, application containers/nginx, hosted entrypoint
  azure.yaml                        hosted Responses declaration
  .foundry/                         metadata and evaluation caches, not runtime source
  docs/design/                      seven independently owned design documents
```

## Seven design documents

| Document | Responsibility |
| --- | --- |
| [prd.md](prd.md) | Product, audience, current capabilities, acceptance and exclusions. |
| [business-rules.md](business-rules.md) | Six demo scenarios, plain-English walkthroughs, approval/resume process and core business rules. |
| [userflow.md](userflow.md) | Three-pane journey, native live observation, pending/failure/resolution states. |
| [architecture.md](architecture.md) | Logical, process, development, physical and scenario views with MAF diagrams. |
| [techstack.md](techstack.md) | Technology roles and authoritative manifest links. |
| [projectstructure.md](projectstructure.md) | This source and ownership map. |
| [issues-changes-fixes.md](issues-changes-fixes.md) | Local changes and MAF-only historical release/incident provenance. |

Deployment, telemetry and evaluation details remain in existing component READMEs,
not extra design topics. Root implementation diagrams have been folded into
architecture/user flow; this lane does not require their continued presence.

## Runtime and packaging ownership

`api/` owns transport, `application/` owns command/query authority and ports, `maf/` owns
native execution, and `infrastructure/` implements adapters. Imports do not open
resources. `bootstrap.py` constructs real or explicitly injected runtimes and owns
their start/close boundaries.

Business routers use service methods for case pages, case/run workspaces, event
reads and selected-run explanation. `application/history.py` owns `CasePage` and
`CaseCursor`; HTTP schemas derive from those contracts rather than reversing the
dependency. The service loads workspace records before calling the synchronous
projection and uses the bootstrap-injected model for safe-fact explanation.
SSE framing, polling, heartbeat, reconnect handling and HTTP errors remain in
routers; readiness alone can use the repository dependency directly.

`backend/migrations/` is the SQL source; wheel and hosted preparation package
generated `_migrations/` resources. Generated copies of `maf_double_charge/`
and `model_to_harness_shared/` under the hosted agent directory are build
artifacts, never another editable source. Installed code uses process environment
and packaged SQL rather than assuming an editable checkout.

The only allowed outside runtime dependency is the
[neutral shared package](../../../../../shared/). No other lane's API/UI,
checkpoint saver, application service, telemetry or release module is imported.
The lane-owned [Compose stack](../../compose.yaml) is an optional local database,
not shared infrastructure. `scripts/with_local_db.py` explicitly selects it for
a child command without changing the application's `.env` or migrating
automatically. See [local PostgreSQL](../../README.md#local-postgresql).

## Scripts and operational documentation

| Surface | Purpose |
| --- | --- |
| `scripts/dev-backend.sh` | Resolve lane root and its `.venv`, run `python -m maf_double_charge.main`; canonical Settings owns host/port/reload. |
| `scripts/migrate.sh`, `scripts/migrate.py` | Explicit reviewed versioned SQL operation; not required for already-ready storage and not run by app startup. |
| `scripts/prune_incompatible_history.py` | Read-only preview by default; guarded, explicitly authorized deletion of incompatible old MAF cases only. |
| `scripts/smoke.py`, `scripts/e2e.py`, `scripts/e2e-browser.sh` | Explicit acceptance against a deliberately selected target; never silently use a real database in unit tests. |
| `scripts/prepare_hosted.py` | Prepare hosted source plus packaged SQL. |
| `scripts/deploy_azure.sh`, `scripts/release.py` | Lane-owned preview/apply and immutable provenance gates; no automatic approval to deploy. |
| `infra/app/update-existing.bicep` | Existing API/UI-only updates selected by `--app-only --update-existing`; foundation resources are not managed by this template. |
| `scripts/hosted_harness.py` | Explicit hosted command/session acceptance and owned-session cleanup. |
| `scripts/prepare_hosted_eval.py`, `scripts/download_eval_results.py` | Pinned evaluation setup and per-row inspection, separate from local deterministic evals. |
| [infra/README.md](../../infra/README.md) | Topology, packaging, release order, update-existing recovery and hosted acceptance. |
| [observability/README.md](../../observability/README.md), [SETUP.md](../../observability/SETUP.md) | Export ownership, safety, native trace interpretation and executed-vs-unexecuted gates. |
| [.foundry/README.md](../../.foundry/README.md) | Metadata/cache boundary and evaluation intent. |

Private `.env`/`.azure` files are operator-owned and must never enter source,
browser bundles, reports or test fixtures. Read [local configuration](../../README.md#local-configuration)
before launching. Tests explicitly ignore actual dotenv; integration uses only
the dedicated test database when separately enabled.
