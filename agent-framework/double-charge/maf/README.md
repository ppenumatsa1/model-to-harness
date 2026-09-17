# Microsoft Agent Framework double-charge app

This independent Python 3.12 + React teaching app turns a deterministic
double-charge support scenario into an inspectable, durable workflow. Microsoft
Agent Framework (MAF) owns the explicit graph, fan-out/fan-in, status events, and
checkpoint resume. PostgreSQL stores application state, selected memory, approvals,
framework-owned MAF checkpoints, the idempotent refund ledger, outcomes, and
append-only audit events.

## Design documentation

This lane independently owns seven design documents:
[product requirements](docs/design/prd.md),
[business scenarios, rules and human approval](docs/design/business-rules.md),
[user flow](docs/design/userflow.md),
[4+1 architecture](docs/design/architecture.md),
[technology stack](docs/design/techstack.md),
[project structure](docs/design/projectstructure.md), and
[issues, changes and fixes](docs/design/issues-changes-fixes.md).

Operational details remain in the lane's [infra guide](infra/README.md),
[observability guide](observability/README.md),
[telemetry setup](observability/SETUP.md), and
[Foundry workspace guide](.foundry/README.md). Historical deployment evidence is
dated separately from current local source capabilities.

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

Policy ineligibility with valid billing evidence closes as `completed_no_refund`;
it is not a technical failure. Missing or invalid required evidence still fails.
Refund attempts exhausted with an uncertain outcome route to `manual_review`
with `refund_outcome_uncertain`, without a success notification. The executor's
retry limit applies per invocation; replay can repeat work, so the durable
ledger and stable idempotency identity remain essential. No automated live-provider
reconciliation is implemented.

## Case workspace

The functional workspace has three panes:

- **History:** all persisted MAF cases, newest first, ten at a time with **Load
  more**. Selecting a case restores its recorded context; the URL preserves that
  selection on reload. **New case** opens a separate editable draft.
- **Execution:** the selected case's context and approval controls, a live
  execution timeline, and state/memory/outcome inspectors. The workflow graph and
  read-only CopilotKit explainer remain available as collapsible supporting views.
- **Audit trail:** business milestones with recorded times, actors, decisions,
  reasons, and supporting evidence. Technical event codes, nodes, and checkpoints
  remain in the execution timeline rather than the business view.

Start and resume remain explicit synchronous HTTP commands. A new UI case has a
fresh client-generated case identity and idempotency key so the browser can
observe its persisted events while Start is still running. A separate optional
UUID `request_id` deduplicates Start in PostgreSQL; the refund idempotency key
does not deduplicate Start. Matching completed retries return the original Start
receipt, while changed intent returns `409 start_request_conflict`. Legacy callers
omitting `request_id` retain fresh-Start behavior.

The UI retains the exact pending command in tab session storage before submitting
it. After an ambiguous response or reload, **Retry same Start request** reuses its
request, case and refund identities; it never silently opens a replacement case.
Successful responses or definite rejections clear the retained command. Storage
errors block submission visibly. The retained complaint is tab-local, not a
credential, and is removed when that tab session ends.

An unfinished durable claim returns `409 start_in_progress` with the original
case/run IDs. A process failure between claim and receipt does **not** authorize
automatic re-execution. Inspect the original case, audit and native checkpoint;
use normal approval/resume commands only when their persisted preconditions hold.
There is no automatic abandoned-claim recovery or claim deletion endpoint.
The original Start receipt is immutable; GET state remains authoritative after
subsequent approval/resume. Migration `002_start_requests.sql` must be applied
explicitly before deploying this source to an existing installation. Startup
only checks readiness and does not migrate. Claims and their referenced runs must
be retained together; deleting a run cannot silently forget its Start identity.

The native SSE stream replays committed PostgreSQL events and follows new writes.
It reconnects from a sequence cursor; safe state/approval/outcome snapshots also
update when no new audit event is written. The UI does not require refresh or
Application Insights to display progress. AG-UI remains a separate additive
projection. Native framework events collected after an invocation are not
presented as if they had been persisted live during execution.

Start and Resume require an explicit nonblank `operator_id` (trimmed, at most 128
characters); new approval/rejection commands require a reviewer and reason.
These requirements apply to application, API, and hosted callers, not just the UI.
Operator and reviewer identities are caller-provided, **not authenticated**.
Automated activity is attributed to System, never to the person who opened the case.
Use explicit hosted JSON commands with `operator_id`; actorless free-text starts
are no longer valid.

Recording a decision does **not** resume the workflow. Reopened cases read that
decision from PostgreSQL, but require a separately entered Resume operator.
The audit distinguishes resume requested from execution continued, refund recorded
from refund verified, and unresolved/manual-review outcomes from successful closure.
Payments and notification sending remain simulated; no external settlement or
delivery receipt is implied. The current-status header is a snapshot, while each
historical milestone uses its own recorded evidence, not today's state.

New events include audit format version 2 and actor metadata in existing JSON
payloads; no database migration is required. The business view is a deterministic
projection, not an LLM-generated account. Browser responses exclude raw idempotency
keys, checkpoint contents, and unrestricted state/memory/tool payloads. Human actor
metadata and reviewer reasons are not added to model facts or general audit logging.

Event inserts are briefly serialized per run before allocating a sequence so
parallel branch commits cannot cause the stream cursor to skip an event. This
does not serialize billing/policy execution or make state, ledger, audit, and
outcome writes one atomic transaction.

## Local setup

From this `maf/` folder:

```bash
uv sync --extra dev
test -e .env || cp .env.example .env
```

The lane's package configuration installs the root shared package as an explicit
local dependency. It owns only framework-neutral domain records, fixtures,
evaluation contracts, and deterministic simulators. This app never imports LangGraph
or another app's code.

For an existing configured database, initialize this app's schema and run the
services below. For isolated local PostgreSQL, use the explicit wrappers in the
next section instead; do not migrate an Azure database while testing locally.

```bash
./scripts/migrate.sh
./scripts/dev-backend.sh
npm --prefix frontend install
npm --prefix frontend run dev
```

The MAF UI uses port `5174` and the API `8010` by default.

### Local PostgreSQL

This project's [compose.yaml](compose.yaml) starts only PostgreSQL 16 on
`127.0.0.1:15432`, database `maf_cutover_tests`, user `mafdev`. Its project name is
`double-charge-maf`; Compose owns a separate `double-charge-maf_default` network
and `double-charge-maf_postgres-data` volume. There are no global container names.
An occupied port causes startup to fail; do not stop unrelated listeners or change
an existing Azure-backed preview to make room.

From this lane directory, generate a private password once (exclusive creation
refuses to overwrite existing settings), then start the database:

```bash
python3 - <<'PY'
import os
import secrets
from pathlib import Path
template = Path(".env.compose.example").read_text()
with os.fdopen(os.open(".env.compose", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
    file.write(template.replace("replace-me", secrets.token_hex(24)))
PY
docker compose --env-file .env.compose config --quiet
docker compose --env-file .env.compose up -d --wait postgres
```

Never print the resolved Compose configuration: it contains the password.
Do not export `POSTGRES_PASSWORD` or `COMPOSE_PROJECT_NAME` overrides; the private
file and explicit project name define this local instance. Keep the password file:
changing it does not change the password of an already initialized volume.

The independently owned wrapper resolves **only this Compose file**, validates its
loopback address/project/port, and passes `DATABASE_URL`, `TEST_DATABASE_URL`, and
the local `DATABASE_SCHEMA=maf_double_charge` to one child process. Process settings
override the application's private `.env`, which remains untouched. It disables
telemetry export, but does not substitute fake models for a real backend.

```bash
.venv/bin/python scripts/with_local_db.py -- .venv/bin/python -m maf_double_charge.infrastructure.persistence.migrations
.venv/bin/python scripts/with_local_db.py -- .venv/bin/python -m pytest backend/tests/integration
# Optional model-backed API; configure the model separately and use an unused port.
.venv/bin/python scripts/with_local_db.py -- env PORT=18010 ./scripts/dev-backend.sh
```

The integration suite uses fake models and randomized, fixture-owned schemas.
It accepts only the dedicated local test database (new port `15432` or legacy
`5434`), not Azure. The URL is passed privately, never via command arguments.
Use the wrapper for any local migration/test/backend command; unwrapped commands
continue to select the application's existing configuration.

```bash
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose stop postgres
docker compose --env-file .env.compose start --wait postgres
```

Stop/start preserves the database and does not affect the other projects.
`down` also retains the volume, but **never use `down -v` or prune volumes**.
The retired root Compose volume is neither reused nor deleted.

### Local configuration

Editable checkout entrypoints select this lane's exact root `.env`, regardless
of launch directory. They do not scan the repository root, a neighboring lane,
`backend/.env`, `frontend/.env`, `.env.local`, or mode-specific dotenv files.
Installed wheels and generated hosted packages use process environment instead
of assuming checkout parents exist.

Python Settings precedence is **explicit constructor values > process environment
> selected dotenv > safe defaults**. `Settings(_env_file=None)` disables dotenv;
`Settings(_env_file=path)` explicitly selects another file. `get_settings()` is
cached, so restart the API after changing configuration. Do not shell-source
dotenv or print its contents.

Dotenv populates Settings, not `os.environ`. Map deployment outputs to the
canonical names in `.env.example` explicitly; arbitrary azd aliases are ignored.
SDK-specific process controls, including `OTEL_SDK_DISABLED`, `OTEL_*_EXPORTER`
and `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS`, must be supplied as process environment
variables rather than relying on this dotenv loader.

`DATABASE_URL` is required for real storage and has no credential-bearing code
fallback. Set `DATABASE_SCHEMA` to the intended existing MAF schema; the default
is `maf_double_charge`. Both `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` are
required for real model-backed execution. Explicit fake app/evaluation factories
disable dotenv and model/export settings; tests do not use the private application
configuration. Preparing `.env` does not initialize, migrate or reset storage.

The launcher resolves its own lane root and `.venv`, then uses canonical
`maf_double_charge.main`. From anywhere in the checkout, use its absolute path:

```bash
/path/to/model-to-harness/agent-framework/double-charge/maf/scripts/dev-backend.sh
npm --prefix /path/to/model-to-harness/agent-framework/double-charge/maf/frontend run dev
```

Direct editable `maf-double-charge` or `python -m maf_double_charge.main`
entrypoints also resolve the lane dotenv independently of cwd. `HOST`, `PORT`
and `APP_ENV` control the API bind and development reload; explicit process
values override dotenv without editing it.

Vite reads the same exact `.env` at dev startup, with process environment taking
precedence. `MAF_UI_PORT` defaults to 5174. Optional `MAF_API_PROXY_TARGET` overrides
the API origin; otherwise it derives from `HOST`/`PORT` (wildcard binds map to
loopback). Proxy URLs reject credentials, query/fragment and non-root paths.
Only these safe server settings are returned; dotenv values are never spread into
client definitions, HTML or bundle environment. Production builds do not load
dotenv. `--mode test` also disables dev dotenv; browser fixtures set explicit
local proxies and refuse to reuse an existing UI server. Restart Vite after changes.

Keep `FRONTEND_ORIGIN` aligned with the actual UI URL (default
`http://localhost:5174`). For example, process overrides `PORT=8110` for the API,
`PORT=8110 MAF_UI_PORT=5274` for Vite, and
`FRONTEND_ORIGIN=http://localhost:5274` for the API keep a non-default local pair
consistent when no explicit proxy override is selected.
See [.env.example](.env.example) for all supported Settings fields, optional
telemetry destinations and restart notes. Keep real `.env`/`.azure` values private.

Schema changes are applied explicitly from `backend/migrations/`, not by API or
hosted-agent startup. The migration runner records applied versions and checksums.
Use an empty MAF-owned schema for this cutover: old unversioned schemas and serialized
checkpoints are intentionally unsupported. Never reset the shared PostgreSQL database
or a LangGraph schema to initialize MAF.

### Removing incompatible business-audit history

Actorless or incompatible history is not backfilled with invented identities.
The maintenance command defaults to a read-only preview and targets only cases
created before an explicit timezone-aware cutoff. Compatibility requires the
version-2 opening record and valid actor/version metadata on recorded events;
an unfinished version-2 case is not incompatible just because later steps are absent.

With the intended MAF `DATABASE_URL` and `DATABASE_SCHEMA` already configured:

```bash
python scripts/prune_incompatible_history.py --before "$CUTOFF"
# Review the counts, stop execution of affected cases, then explicitly confirm.
python scripts/prune_incompatible_history.py --before "$CUTOFF" \
  --apply --confirm-schema "$DATABASE_SCHEMA" --confirm-count "$EXPECTED_CASES"
```

Deletion removes only targeted case records and their owned events, approvals,
outcomes, selected memory, MAF checkpoints, and simulated refund-ledger records.
It runs in one transaction with scoped table locks and refuses changed candidate
counts, running targets, or refund records referenced by retained cases. It does
not drop tables, reset sequences, migrate schemas, or touch LangGraph.

Existing cloud API/hosted versions must be updated before using them with the new
actor contract; an older deployed writer can produce incompatible history again.
Local source changes and history cleanup do not themselves deploy those versions.

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
  -d '{"operator_id":"operator-1","complaint":"I was charged twice.","customer_id":"customer-100","scenario_id":"duplicate-confirmed"}'
```

The start response pauses with a `run_id` and `checkpoint_id`. Record a decision,
then resume:

```bash
curl -s -X POST "$BASE/api/runs/$RUN_ID/approval" \
  -H 'content-type: application/json' \
  -d "{\"checkpoint_id\":\"$CHECKPOINT_ID\",\"decision\":\"approve\",\"reviewer_id\":\"reviewer-1\",\"reason\":\"Reviewed duplicate-charge evidence.\"}"
curl -s -X POST "$BASE/api/runs/$RUN_ID/resume" \
  -H 'content-type: application/json' \
  -d "{\"checkpoint_id\":\"$CHECKPOINT_ID\",\"operator_id\":\"resumer-1\"}"
```

Other useful endpoints:

- `GET /api/cases?limit=10&cursor=<next_cursor>` for keyset-paginated history
- `GET /api/cases/{case_id}` for a safe historical workspace snapshot
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/events?after=0&limit=200`
- `GET /api/runs/{run_id}/events/stream?after=0` for resumable native SSE
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

## Historical deployed teaching environment - 2026-09-10

The following is recorded release evidence, **not a current remote-health check**.
It predates the local policy/uncertainty corrections, case workspace, operator
contract and business audit v2 described above. Those source changes and the
lane-local configuration work have not been deployed by this task.

- Public application:
  <https://mth-maf-wh2su65huqw5o-web.livelyhill-0f2b68f2.northcentralus.azurecontainerapps.io>
- Foundry project: `model-harness-maf`
- Hosted Agent: `model-harness-maf` version 8
- Model: `gpt-5.6-sol` version `2026-07-09`, Global Standard
- Region/resource group: `northcentralus` / `rg-model-harness`
- Fresh application/checkpoint schema: `maf_double_charge_cutover`
- API/frontend ready revisions: `0000005`, built from `6948226`
- Hosted source: `73c8693`, with fixed 100% native sampling and a startup-only
  correction that honors the hosted SDK/HTTP instrumentation opt-outs;
  verified archive SHA-256
  `5875ffe17d0ce5f7446cc282861cbd19d573f5d5e07ea431dbec3d147e202f7b`
- Latest cloud evaluation (version 5): **4 passed, 0 failed, 0 errored, 0 unscored**,
  reproduced from repository configuration with pinned task-completion 19 and
  relevance 12 evaluators. The reviewed suite is retained; judge scoring was not
  rerun for the sampling/instrumentation-only follow-up deployments.

All seven API scenarios, all seven explicit hosted-command scenarios, and browser
E2E passed. Read-only PostgreSQL checks verified approvals, checkpoint persistence,
one matching refund where required, verification results, and no false-success
notifications for all 14 refreshed API/hosted scenario runs. The hosted rerun used
the explicit `--transport sdk` acceptance option after intermittent local azd
credential-subprocess failures; it executes the same commands without request
retries. Native telemetry, cross-session correlation and scoped safety checks
also passed. Historical scoring failures remain recorded, not relabeled.
The subsequent screenshot review exposed a default rate-limited sampling defect
that dropped native parent spans. Version 6 fixes this with supported fixed 100%
sampling, without replacing the hosted provider or changing workflow code.
All seven hosted scenarios passed again: all 12 actual workflow executions had
the exact expected executor branches, linked agent/model parents and no orphaned
native parents. The five approval-only commands correctly have no workflow spans.
The user confirmed full version-6 flows in both Foundry and Application Insights.
Version 8 additionally removes SDK bookkeeping and generic outgoing HTTP
auto-instrumentation without removing native workflow spans. Its seven-scenario
rerun has **zero SDK setup spans, zero HTTP transport spans, 12 complete workflow
executions and 10 model calls**. All 17 verification sessions are idle.
The recorded no-duplicate trace `5a2f13378426a7b2691f2a9ab1692dd2` at
`2026-09-10T16:07:48Z` has all 15 native spans and passes the per-operation gate.
The old broken screenshot trace and empty telemetry fail that gate.
Use the [command-only index](observability/command-traces.kql) for a clean list
that retains failed and approval-only commands. Operational logs remain available;
old traces/noise cannot be repaired or removed retroactively by this deployment.

Failed version 4 was deleted without force. Versions 1-3 remain nondefault with
ten idle teaching sessions: Foundry rejected nonforced deletion, and forcing it
would cascade-delete their sessions/files. That destructive cleanup is deferred;
the old SQL schema and audit records are retained. The new runtime neither reads
nor converts old records/checkpoints. See the
[issue ledger](docs/design/issues-changes-fixes.md) for source hashes,
evaluation IDs, evidence, and the cleanup limitation. Work remains on the feature
branch; no push or merge to `main` has been performed.

The deployment is educational and is not a production network or payment-system
reference.

The Foundry project is connected through IaC to the lane-owned Application Insights
resource. Hosted Responses traces preserve MAF's native `workflow.run`,
edge-group, executor, model, and message-send hierarchy. Hashed case/run IDs join
separate commands while their supplied conversation/response IDs remain distinct.
