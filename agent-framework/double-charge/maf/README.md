# Microsoft Agent Framework double-charge app

This independent Python 3.12 + React teaching app turns a deterministic
double-charge support scenario into an inspectable, durable workflow. Microsoft
Agent Framework (MAF) owns the explicit graph, fan-out/fan-in, status events, and
checkpoint resume. PostgreSQL stores application state, selected memory, approvals,
framework-owned MAF checkpoints, the idempotent refund ledger, outcomes, and
append-only audit events.

## What the example teaches

- Explicit nodes and conditional edges rather than a hidden agent loop.
- Parallel billing and refund-policy validation with a synchronized join.
- A durable approval pause: `POST /approval` records a command and `POST /resume`
  separately resumes the saved MAF checkpoint.
- Bounded retries plus explicit failure and manual-review routes.
- A PostgreSQL-durable refund ledger with stable idempotency keys, request
  fingerprint conflict detection, and independent verification after restart.
- MAF-native events stored alongside application audit events.
- An additive AG-UI projection; it is not a workflow command bus.
- A real read-only CopilotKit AG-UI runtime invoked through `useAgent`; it exposes
  allowlisted selected-run facts and no workflow command tools.
- A browser-safe distinction between workflow state, selected memory, audit
  history, and temporary model context.

The UI and API expose concise business evidence, never chain-of-thought, raw
prompts, credentials, unrestricted tool payloads, or raw checkpoint contents.

## Local setup

From this `maf/` folder:

```bash
uv sync --extra dev
cp .env.example .env
```

The lane's package configuration installs the root shared package as an explicit
local dependency. It owns only framework-neutral domain records, fixtures,
evaluation contracts, and deterministic simulators. This app never imports LangGraph
or another app's code.

Start PostgreSQL using the repository-level developer dependency when available,
then initialize this app's schema and run the services:

```bash
./scripts/migrate.sh
./scripts/dev-backend.sh
npm --prefix frontend install
npm --prefix frontend run dev
```

The MAF UI uses port `5174` by default so it can run beside the independent
comparison app.

Schema changes are applied explicitly from `backend/migrations/`, not by API or
hosted-agent startup. The migration runner records applied versions and checksums.
Use an empty MAF-owned schema for this cutover: old unversioned schemas and serialized
checkpoints are intentionally unsupported. Never reset the shared PostgreSQL database
or a LangGraph schema to initialize MAF.

## Source map

The installable package remains `backend/src/maf_double_charge/`:

| Area | Responsibility |
| --- | --- |
| `api/` | FastAPI factory, HTTP contracts, routers, and dependency injection |
| `application/` | Commands, authoritative records, service interfaces, refunds, and audit |
| `maf/` | Agent definitions, prompts, native executors, graph composition, and resume |
| `infrastructure/` | PostgreSQL/checkpoint adapters, migrations, simulators, and telemetry |
| `projections/` | Browser-safe AG-UI, selected-run facts, and workflow visualization |
| `testing/` | Explicit test doubles; never an automatic production fallback |
| `bootstrap.py` | MAF-local runtime construction and resource lifecycle |

Start with `maf/workflows/double_charge.py` for the graph,
`maf/executors/approval.py` for its durable pause, and `application/refunds.py` for
idempotency and verification. SQL source remains outside the package in
`backend/migrations/`; installed and hosted bundles contain generated resource copies.

Real local runs require:

```text
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL=<deployment-name>
```

Authentication uses `DefaultAzureCredential`; for local development, sign in
with Azure CLI. Tests inject `FakeModelClient` and require no cloud access.

## API flow

```bash
curl -s http://127.0.0.1:8010/api/scenarios
curl -s -X POST http://127.0.0.1:8010/api/cases \
  -H 'content-type: application/json' \
  -d '{"complaint":"I was charged twice.","customer_id":"customer-100","scenario_id":"duplicate-confirmed"}'
```

The start response pauses with a `run_id` and `checkpoint_id`. Record a decision,
then resume:

```bash
curl -s -X POST "$BASE/api/runs/$RUN_ID/approval" \
  -H 'content-type: application/json' \
  -d "{\"checkpoint_id\":\"$CHECKPOINT_ID\",\"decision\":\"approve\",\"reviewer_id\":\"reviewer-1\"}"
curl -s -X POST "$BASE/api/runs/$RUN_ID/resume" \
  -H 'content-type: application/json' \
  -d "{\"checkpoint_id\":\"$CHECKPOINT_ID\"}"
```

Other useful endpoints:

- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/events?after=0`
- `GET /api/runs/{run_id}/ag-ui?after=0`
- `GET /api/runs/{run_id}/outcome`
- `GET /api/copilotkit`, `GET /api/copilotkit/info`, and
  `POST /api/copilotkit/agent/selected-run/run`
- `GET /api/copilotkit/runs/{run_id}`
- `GET /health/live` and `GET /health/ready`

## Foundry workspace boundary

`eval.yaml` at this agent root records local evaluation intent. The executable,
framework-specific runner remains `evals/run.py`. The `.foundry/` directory contains
only the canonical single-environment metadata overlay plus suite, dataset,
evaluator, and result caches.

Runtime prompts, agent instructions, deterministic tools, and workflow code stay in
`backend/src/maf_double_charge/`; they are never stored in `.foundry`. No remote
suite, endpoint, resource, azd environment, or deployment is claimed by the local
overlay.

## Validation

```bash
uv run ruff check backend evals scripts
uv run pytest
uv run python evals/run.py
npm --prefix frontend test
npm --prefix frontend run build
```

PostgreSQL integration tests require a dedicated disposable database, not the
ordinary application database. CI uses this same loopback-only test contract:

```bash
docker run --name maf-integration-db --rm -d \
  -p 127.0.0.1:5434:5432 \
  -e POSTGRES_USER=mafdev \
  -e POSTGRES_PASSWORD=local-development-only \
  -e POSTGRES_DB=maf_cutover_tests postgres:16-alpine
docker exec maf-integration-db pg_isready -U mafdev -d maf_cutover_tests
export TEST_DATABASE_URL='postgresql://mafdev:local-development-only@127.0.0.1:5434/maf_cutover_tests'
uv run pytest -c pyproject.toml ../../../shared/tests backend/tests
```

Wait for `pg_isready` to report accepting connections before running tests. The
fixtures create and remove unique test schemas; they reject other database targets.
Without `TEST_DATABASE_URL`, these PostgreSQL tests are skipped. Stop only the
container created above when finished: `docker stop maf-integration-db`.

With the API running:

```bash
uv run python scripts/smoke.py
uv run python scripts/e2e.py
./scripts/e2e-browser.sh
```

See `observability/README.md`, `infra/README.md`, and `.foundry/README.md` for
release, evaluation, and telemetry boundaries.

## Deployed teaching environment

- Public application:
  <https://mth-maf-wh2su65huqw5o-web.livelyhill-0f2b68f2.northcentralus.azurecontainerapps.io>
- Foundry project: `model-harness-maf`
- Hosted Agent: `model-harness-maf` version 5
- Model: `gpt-5.6-sol` version `2026-07-09`, Global Standard
- Region/resource group: `northcentralus` / `rg-model-harness`
- Fresh application/checkpoint schema: `maf_double_charge_cutover`
- API/frontend ready revisions: `0000004`, built from `c460769`
- Hosted source: `29b81e7` (same runtime code; hosted package-index correction)
- Hosted evaluation acceptance: **blocked**. Two four-case runs each returned
  0 passed, 0 failed, and 4 scoring errors despite producing the agent responses.

All seven API scenarios, all seven explicit hosted-command scenarios, and browser
E2E passed. Read-only PostgreSQL checks verified approvals, checkpoint persistence,
one matching refund where required, verification results, and no false-success
notifications for 15 runs, including recovery after stopped hosted sessions.
The evaluation service returned no per-item scoring reasons. A separate probe
confirmed the configured judge rejects `temperature=0`; no model change or
undocumented cloud-evaluator override was applied. See the
[issue ledger](../../../docs/design/issues-changes-fixes.md) for retained run IDs
and the unresolved acceptance gate. The feature branch is not merge-ready.
Older hosted-version definitions and the old schema remain isolated from the new
default deployment; retirement of those serving paths is deferred until acceptance.
The new runtime does not read or convert old records/checkpoints.

The deployment is educational and is not a production network or payment-system
reference.

The Foundry project is connected through IaC to the lane-owned Application Insights
resource. Hosted Responses traces preserve MAF's native `workflow.run`,
edge-group, executor, model, and message-send hierarchy. Hashed case/run IDs join
separate commands while their supplied conversation/response IDs remain distinct.
