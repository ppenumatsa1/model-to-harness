# Double-charge workflow: LangGraph

An independent Python 3.12/FastAPI + React/Vite teaching app. It uses an idiomatic
`StateGraph`, conditional routes, parallel billing/policy branches, reducer-backed
evidence, bounded retry routes, and `interrupt()`/`Command(resume=...)` with a
PostgreSQL checkpointer. Application audit records live in separate
`langgraph_app_cutover.*` tables. Checkpointer migrations run through a psycopg
connection whose `search_path` is pinned to `langgraph_checkpoints_cutover`, so no
saver table is created in `public`; checkpoint internals are never exposed.

The backend separates `api`, `application`, native `graph`, `infrastructure`,
`projections`, and explicit `testing` doubles. `bootstrap.open_runtime()` owns
composition and cleanup for API and hosted entrypoints. Hosted startup verifies
storage, then each explicit command owns and releases its own database/model
resources; idle hosted compute retains no application pool or native saver
connection. Old flat-module imports are
removed without aliases. This is a fresh-state cutover, not a legacy-data migration.

Policy ineligibility with valid billing evidence normalizes to
`completed_no_refund`, not a technical failure. Missing or invalid required
evidence still fails. Refund attempts exhausted with an uncertain outcome,
including responses without a refund ID, route to `manual_review` with
`refund_outcome_uncertain`; no success notification is sent. Attempts are recorded
in graph state, but recovery can replay work since the last checkpoint. Provider
idempotency and reconciliation remain application responsibilities; this demo
does not perform live-provider reconciliation.

## Local setup

Configuration belongs to this lane's private `.env`, not the launch directory.
Explicit `Settings(...)` values override process environment, which overrides the
selected dotenv file, then safe defaults. `_env_file=None` disables dotenv;
`_env_file=path` selects an explicit alternative. Installed wheels and hosted
packages use process environment by default and do not search checkout parents.

```bash
cd agent-framework/double-charge/langgraph
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ../../../shared
pip install -e ".[dev,observability]"
test -e .env || cp .env.example .env
# For an existing database, fill DATABASE_URL and model settings privately.
# For isolated local PostgreSQL, use the Local PostgreSQL wrappers below instead.
PYTHONPATH=backend/src python scripts/setup_db.py
./scripts/dev-backend.sh
```

In another shell:

```bash
cd frontend
npm install
npm run dev
```

Real runs require `DATABASE_URL`, `AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_DEPLOYMENT` and an identity available through
`DefaultAzureCredential`. There is no database credential fallback, automatic
schema setup or silent fake-model fallback. `HOST`/`PORT` default to
`127.0.0.1:8000`; `FRONTEND_HOST`/`FRONTEND_PORT` default to `localhost:5173`.
`BACKEND_PROXY_URL` optionally overrides the server-only proxy (otherwise derived
from backend host/port); `CORS_ORIGINS` should match the chosen browser origin.

After installation, launch from any directory using the absolute path to
`scripts/dev-backend.sh`, or from the repository root:

```bash
agent-framework/double-charge/langgraph/scripts/dev-backend.sh
npm --prefix agent-framework/double-charge/langgraph/frontend run dev
```

The backend script selects this lane's `.venv/bin/python` and resolved source
paths. With the editable package installed, the same interpreter can run
`-m model_to_harness_langgraph.infrastructure.persistence.migrations --verify-only`
from any directory. Restart backend and Vite after configuration edits.
See [.env.example](.env.example) and the
[canonical configuration table](docs/design/techstack.md#backend-configuration-contract).

Optional local telemetry uses the resolved Settings connection string,
service name and app environment. `TELEMETRY_ENABLED=false` prevents local
exporter installation; hosted SDK providers remain SDK-owned and safety-checked.
Vite selects only safe server fields, never dotenv secrets or `VITE_*` keys into
browser environment/bundles. Tests explicitly disable dotenv and local telemetry,
using fake models and in-memory checkpointer/audit repositories:

```bash
pytest
cd frontend && npm install && npm test && npm run build
```

`./scripts/browser-e2e.sh` starts an in-memory fake-model backend plus Vite, runs
Playwright, and cleans up both processes. It uses separate default ports
18000/15173, an explicit loopback fake-backend proxy, and rejects occupied ports;
test-only process overrides are `E2E_BACKEND_PORT` and `E2E_FRONTEND_PORT`.
It does not run against the interactive preview. Install the Playwright Chromium binary once
with `cd frontend && npx playwright install chromium`.

Database setup uses the application virtual environment plus Psycopg; it does not
require a host `psql` executable. Application SQL is authoritative in
`backend/migrations/` and packaged in the wheel. Native saver migrations remain
framework-owned. Run explicit setup before serving, then use read-only verification:

```bash
PYTHONPATH=backend/src python scripts/setup_db.py
PYTHONPATH=backend/src python scripts/setup_db.py --verify-only
```

Set the process-only `TEST_DATABASE_URL` to a dedicated loopback PostgreSQL database to run reconstruction,
durable-refund, and schema-isolation integration coverage.
The fixture creates/drops randomized paired schemas and rejects remote database
hosts. It never loads the test URL from a private lane dotenv file.
Use fresh paired schemas instead of dropping application records while retaining
unrelated checkpoints. Runtime startup never applies DDL or silently selects a fake.

### Local PostgreSQL

This lane's [compose.yaml](compose.yaml) starts only PostgreSQL 16 at
`127.0.0.1:25432`, database `double_charge_lg_local`, user `lgdev`.
Project `double-charge-lg` owns network `double-charge-lg_default` and volume
`double-charge-lg_postgres-data`; it has no globally named container. It can run
alongside both MAF databases. An occupied port makes startup fail visibly; never
stop unrelated listeners or switch an existing Azure-backed preview for this setup.

From this lane directory, create separate private Compose settings once:

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

Exclusive file creation refuses to overwrite existing settings. Never print the
resolved Compose configuration (it includes credentials), shell-source dotenv, or
replace the application's `.env`. Do not export `POSTGRES_PASSWORD` or
`COMPOSE_PROJECT_NAME` overrides. Keep `.env.compose`: changing it does not change
the password stored in an initialized database volume.

The lane-owned wrapper validates this Compose project's loopback binding and
provides canonical `DATABASE_URL` and `TEST_DATABASE_URL` only to its child process.
It also explicitly selects `LANGGRAPH_SCHEMA=langgraph_app_local` and
`LANGGRAPH_CHECKPOINT_SCHEMA=langgraph_checkpoints_local`. These process settings
override the lane's private `.env` without editing it. Exporters are disabled.

```bash
.venv/bin/python scripts/with_local_db.py -- .venv/bin/python scripts/setup_db.py
.venv/bin/python scripts/with_local_db.py -- .venv/bin/python scripts/setup_db.py --verify-only
.venv/bin/python scripts/with_local_db.py -- .venv/bin/python -m pytest backend/tests
# Optional model-backed API; configure the model separately and use an unused port.
.venv/bin/python scripts/with_local_db.py -- env PORT=18000 ./scripts/dev-backend.sh
```

Tests explicitly use fake models and fixture-owned randomized schemas; the local
database selection never enables cloud models or telemetry. The wrapper itself
does not replace the real backend's model. Unwrapped commands retain the existing
application configuration, so use the wrapper for every local migration/test/run.

```bash
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose stop postgres
docker compose --env-file .env.compose start --wait postgres
```

Stop/start preserves state without affecting another project. `down` retains the
volume, but never use `down -v` or prune volumes. The retired root Compose volume
is not reused, migrated, or deleted.

## API flow

1. `POST /api/cases` requires an operator identity and runs until terminal state
   or the durable approval interrupt. The UI can observe the committed case while it runs.
2. `POST /api/cases/{case_id}/approval` records a reviewer decision and required reason.
   The command is insert-once: an identical retry is accepted, while any changed
   checkpoint, decision, reviewer, or reason conflicts and cannot replace it.
3. `POST /api/cases/{case_id}/resume` requires the current checkpoint and a Resume
   operator, then supplies the recorded decision through `Command(resume=...)`.
4. `GET /api/cases` pages through history; `/api/cases/{case_id}/workspace`
   returns safe context, memory/outcome, persisted approval and command eligibility.
5. `/api/cases/{case_id}/events/stream` follows committed native events and
   independent workspace snapshots. AG-UI remains an additive projection.

The three-pane workspace separates history, execution/controls and business audit.
Record approval/denial and Resume are separate buttons. Human identities are
caller-supplied, not authenticated. New audit records distinguish actors and
actual continuation; legacy missing facts remain unknown. Selected memory is
empty while paused and retained at completion. The demo picker has six choices;
the mismatch fixture remains available to regression/evaluation harnesses.

The UI exposes only allowlisted summaries, tool metadata, retries, approval state,
selected memory, and normalized outcomes. It never exposes prompts, model reasoning,
secrets, checkpoint payloads, or database internals.

### CopilotKit boundary

The CopilotKit provider uses `runtimeUrl="/api/copilotkit"`, discovers the read-only
agent through `GET /api/copilotkit/info`, and invokes
`POST /api/copilotkit/agent/selected-run/run` with AG-UI `RunAgentInput`. The v2
`useAgent` binding scopes `runtimeAgentId="selected-run"` to the selected case thread;
it does not bypass the runtime with a custom fetch. The backend validates `threadId`
and `runId`, then discards arbitrary messages, state, tools, context, and
`forwardedProps`. It reads allowlisted durable events and cannot start, approve, or
resume a workflow. Those operations remain explicit case command endpoints.

Refund simulator results are persisted in the configured application schema's `refunds` table before an uncertain
response is surfaced. The idempotency key is unique and bound to a deterministic
request fingerprint, allowing reconstruction to return exactly one refund or reject a
conflicting request.

## Shared package boundary

Production wiring imports deterministic fixtures and simulators from
`model_to_harness_shared` at the planned root path `../../../shared/src`. The adapter
is intentionally narrow and duck-types the shared records so this app remains
independently packaged. Tests inject a local fake gateway and do not duplicate the
production simulator.

See [observability](observability/README.md), [infrastructure](infra/README.md),
and [Foundry metadata](.foundry/README.md).

## Lane-owned design

This lane independently owns seven design documents:

| Document | Scope |
| --- | --- |
| [Product requirements](docs/design/prd.md) | Current capabilities and acceptance boundaries. |
| [Business scenarios and rules](docs/design/business-rules.md) | Six scenarios, walkthroughs, approval/resume process and core rules. |
| [User flow](docs/design/userflow.md) | Three-pane workspace, history, native event streaming and explicit controls. |
| [Architecture](docs/design/architecture.md) | Logical, process, development, physical and scenario views. |
| [Technology and configuration](docs/design/techstack.md) | Dependency roles, canonical variables and launch behavior. |
| [Project structure](docs/design/projectstructure.md) | Real package, tests, scripts, artifacts and ownership. |
| [Issues, changes and fixes](docs/design/issues-changes-fixes.md) | LangGraph provenance and local versus deployed evidence. |

## Independent Azure deployment

This lane now includes its own `azure.yaml`, Bicep, images, nginx configuration, and
deployment scripts. Nothing is shared with the MAF deployment.

- Local development and the FastAPI Container App remain on Python 3.12.
- The Foundry hosted agent uses direct-code `codeConfiguration` with
  `python_3_13` and the Responses `2.0.0` protocol.
- `infra/main.bicep` uses the resolved existing region and references the lane's
  Foundry account/project, model and supporting resources. The release template
  manages only the two Container Apps; it does not rewrite infrastructure,
  permissions or monitoring connections as a side effect of an application update.
- The frontend is the only public Container App. nginx serves React and proxies
  `/api`, `/health`, and `/ready` to the internal FastAPI app.

The current hosted adapter requires explicit JSON commands with human identities;
actorless plain-text starts are invalid:

```json
{"action":"start","operator_id":"operator-1","complaint":"I was charged twice.","customer_id":"customer-1"}
{"action":"approval","case_id":"case-id","checkpoint_id":"checkpoint-id","decision":"approve","reviewer_id":"reviewer-1","reason":"Reviewed duplicate evidence."}
{"action":"resume","case_id":"case-id","checkpoint_id":"checkpoint-id","operator_id":"resumer-1"}
```

Approval only records the durable command. Resume remains a separate explicit
operation. Responses contain case status, normalized outcome, and allowlisted event
summaries; they omit prompts, reasoning, workflow state, event data, tool payloads,
credentials, and checkpoint internals.

These workspace/actor changes are local source changes, not a new cloud rollout.
The historical hosted version below predates them. Foundry deployment remains
deferred until local review and approval.

Release tooling discovers the existing lane environment and previews ARM changes
without mutation by default. Local validation and independent review precede apply.
The selected existing PostgreSQL server must be running, and apply requires clean,
committed lane source:

```bash
./scripts/deploy_azure.sh --environment langgraph
./scripts/deploy_azure.sh --environment langgraph --apply
```

Apply uses allowlisted source staging, ACR remote builds and verified immutable image
digests, a final what-if gate, explicit fresh paired-schema setup and healthy app
rollout verification. `--update-existing` verifies the already-deployed schema pair
without migrations or resets. Foundry direct-code deployment remains a separate
explicit step after setting the same schema pair in the selected azd environment.
Prepare with `python scripts/prepare_hosted.py`; verify the actual hosted
version/environment/archive with `scripts/verify_hosted_package.py`.

`scripts/api_harness.py --base-url URL` covers seven case-command scenarios;
`scripts/hosted_harness.py --environment langgraph --version VERSION --transport sdk`
uses fresh conversations and owned version-pinned sessions, stopping compute in
`finally` without deleting state. Both accept `--smoke`. Transport selection is
explicit and never an automatic retry of a potentially mutating command.

The deterministic suite is `python evals/run.py`. Hosted intent lives at
`infra/foundry-hosted/agent/eval.yaml`; `scripts/prepare_hosted_eval.py` validates the
four reviewed cases and catalog pins, verifies the selected version, creates a fresh
group and emits a private batch-evaluation request. `scripts/download_eval_results.py`
persists every result and fails on missing, failed, errored or unscored decisions.

### Verified cutover release - 2026-09-10

| Surface | Verified release / evidence |
| --- | --- |
| API / frontend | Source `901634a`, revisions `0000014` / `0000009`; private API and public frontend retained. |
| Foundry | Agent/project `model-harness-langgraph`, hosted version **15**, source `1e99986`; downloaded archive, Python 3.13 runtime and environment attested. |
| End-to-end | Seven API and seven hosted scenarios, direct PostgreSQL evidence and deployed browser approval/resume passed. |
| Cloud judges | v15: **4/4 passed**, zero failed/errored/unscored; task-completion 19 and relevance 12. |
| Telemetry | Hosted matrix: 17 commands, 12 workflows, 70 node executions and 10 native model calls. Exact branches, retries, usage, internal parents and complete retention verified; zero HTTP transport spans. API internal hierarchy independently verified. |
| Privacy / cleanup | Release-window key/content-signature checks passed; all 46 task-owned sessions idle, without deleting persisted state. |

Public app:
<https://mth-lg-2vq7rokaqwhae-web.mangodune-3886db41.northcentralus.azurecontainerapps.io>.
App Insights: `mth-lg-2vq7rokaqwhae-appi`.
Final evaluation: `eval_8cdf767bc2994123822a531d8414fa4e` /
`evalrun_83c0674c78af4e1488263f7646318db0`.
See the [implementation ledger](docs/design/issues-changes-fixes.md) for
immutable image/archive digests, incident evidence and remaining teaching
constraints. No legacy-data migration, destructive cleanup, push or merge was
part of this cutover.

### Historical pre-cutover baseline

- Public application:
  <https://mth-lg-2vq7rokaqwhae-web.mangodune-3886db41.northcentralus.azurecontainerapps.io>
- Foundry project: `model-harness-langgraph`
- Hosted Agent: `model-harness-langgraph` version 13
- Model: `gpt-5.6-sol` version `2026-07-09`, Global Standard
- Region/resource group: `northcentralus` / `rg-model-harness`
- Hosted evaluation: 2 passed, 0 failed, 0 errored

The public FastAPI smoke and remote Hosted Agent test both completed separate start,
approval, and resume commands. The retry-safe case produced one PostgreSQL refund
ledger row and one distinct refund ID before notification.

The historical version-13 Application Insights implementation showed `foundry.responses.invoke` followed by
`workflow.run`, framework-local `workflow.node.*` spans, the model dependency, and
safe deterministic tool spans. Start, approval, and resume remain separate operations
linked by conversation, case, and run identifiers. Node and deterministic tool spans
are projected from durable audit timestamps; the real model dependency remains
auto-instrumented. Prompts, complaint text, checkpoint bodies, tool arguments/results,
and credentials were excluded. The cutover replaces those reconstructed node/tool
spans with real execution spans and hashes cross-command identifiers. This historical
deployment/evaluation evidence is not acceptance of the new cutover; see the
[implementation ledger](docs/design/issues-changes-fixes.md) for current gates.
