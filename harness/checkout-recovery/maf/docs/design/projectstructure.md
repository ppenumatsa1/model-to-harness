# MAF checkout project structure

Paths below are relative to this checkout MAF lane. The seven-document layout
matches double-charge MAF, but its source, contracts and runtime remain independent.

```text
maf/
  README.md, AGENTS.md               local entrypoint and lane boundaries
  pyproject.toml, uv.lock            Python manifest and lock
  compose.yaml                      lane-owned PostgreSQL-only stack
  .env.compose.example              local database configuration template
  .env.compose, .azure/              private operator/release configuration
  backend/
    src/checkout_recovery_maf/
      main.py, __main__.py           API factory export and settings-aware launcher
      config.py                     Settings and runtime validation
      bootstrap.py                  checkout-only resource construction/lifecycle
      api/
        app.py                      FastAPI factory, lifespan and authentication
        contracts.py                HTTP command schemas
        dependencies.py             active service and runtime-health dependencies
        routers/cases.py            explicit commands and safe queries
        routers/health.py           live/ready endpoints
      application/
        service.py                  business state machine and safe query assembly
        models.py, ports.py         application records and adapter contracts
        commands.py, errors.py      lane-owned command and failure contracts
      maf/
        investigation.py            actual bounded harness and explicit scripted mode
        diagnostics.py, adapter.py  diagnostic/tool boundary helpers
        skills/checkout-triage/     framework procedural skill
      infrastructure/
        postgres.py, memory.py      repository implementations
        telemetry.py                application spans and content-safe exporter
      projections/safe.py           pure safe case/audit/artifact projections
      testing/                      explicitly injected test doubles
    migrations/                     two versioned application/framework SQL files
    tests/                          flat lane-owned backend tests
  frontend/
    src/                            selected-case UI, API client, state and persistence
    e2e/                            seven fixtures and ambiguous-start browser test
    nginx/                          private-token proxy, optional browser login
    Dockerfile                      repository-root build context
    package.json, package-lock.json  frontend manifest and lock
  scripts/                          local database, packaging, release and acceptance
  evals/                            command matrix and deterministic evaluator
  observability/                    safe telemetry guidance and KQL
  infra/
    app/                            app and foundation Bicep
    foundry-hosted/agent/            Responses entrypoint and generated package copies
      .agentignore                  canonical upload exclusions
      eval.yaml                     tracked evaluation intent
      .foundry/                     metadata and private evaluation caches/results
  azure.yaml                        independent Hosted service declaration
  docs/design/                      seven lane-owned design documents
```

## Seven design documents

| Document | Responsibility |
| --- | --- |
| [prd.md](prd.md) | Current capabilities, audience, safety, acceptance and non-goals. |
| [business-rules.md](business-rules.md) | Seven scenario walkthroughs, approval/resume and deterministic business rules. |
| [userflow.md](userflow.md) | Selected-case UI, refresh, explicit commands and ambiguous Start recovery. |
| [architecture.md](architecture.md) | Logical, process, development, physical and scenario views. |
| [techstack.md](techstack.md) | Technology roles and authoritative manifests. |
| [projectstructure.md](projectstructure.md) | Source map, ownership and operational entrypoints. |
| [issues-changes-fixes.md](issues-changes-fixes.md) | Checkout-only changes, review findings, releases, failed attempts and limitations. |

Approval is part of business rules, as in the reference lane; it is not an
extra lane design file. The parent [domain documents](../../../docs/README.md)
remain separate, framework-neutral requirements for future implementations.

## Runtime and packaging ownership

The composition flow is `main -> api/app -> bootstrap` for host setup.
Request execution is `router -> service -> repository -> PostgreSQL`, with
service-owned read projection assembly on the return path. Projections are
functions and response models, not database schemas or background workers.

The API and Hosted adapter share only this lane's runtime factory and service.
No imports from double-charge or a future checkout sibling are permitted.
The [neutral shared package](../../../../../shared/) contains domain models,
simulator behavior, fixtures and evaluation contracts, not runtime adapters.

`prepare_hosted.py` generates the two Hosted package copies from canonical
source, excluding testing/cache files. Their tracked presence does not make
them alternate source roots. The required root upload files include `eval.yaml`;
the `.foundry/` metadata/caches it references remain outside runtime archives.

PostgreSQL migration files remain in `backend/migrations/` and are applied by
an explicit migration command. Startup opens/checks storage but does not
automatically migrate or reset it. Development may explicitly use memory or
scripted investigation; neither is a production failure fallback.

## Scripts and operational documentation

| Surface | Purpose |
| --- | --- |
| `scripts/with_local_db.py` | Select the independent Compose database for one child command; no automatic migration. |
| `scripts/migrate.py` | Explicit versioned SQL/checksum operations on a deliberately chosen database. |
| `scripts/prepare_hosted.py` | Generate packages and expose exact downloaded-archive verification. |
| `scripts/release.py` | Initial provisioning steps and separately guarded `update-existing` image-only preview/apply. |
| `scripts/verify_hosted.py` | Pinned Hosted smoke/E2E, retained command identities and safe results. |
| `scripts/e2e.py`, `scripts/verify_business.py` | Explicit API matrix and independent persisted business evidence checks. |
| `scripts/prepare_evals.py`, `scripts/verify_evals.py` | Prepare and validate the seven start-only evaluation contracts. |
| `scripts/register_native_evaluation.py`, `scripts/collect_evaluation.py` | Native exact-contract evaluation setup and complete per-item collection. |
| [Infra README](../../infra/README.md), [lane delivery](../../README.md#delivery) | Topology, private settings and release procedures. |
| [Observability README](../../observability/README.md) | Export ownership, safe queries and known limits. |

The ledger moved from `docs/issues-changes-fixes.md` into `docs/design/` with
its history preserved. Navigation points to the canonical file rather than
maintaining duplicate ledgers or shared/generated design documents.
