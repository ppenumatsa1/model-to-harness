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
composition and cleanup for API and hosted entrypoints. Old flat-module imports are
removed without aliases. This is a fresh-state cutover, not a legacy-data migration.

## Local setup

```bash
cd agent-framework/double-charge/langgraph
docker compose -f ../../../compose.yaml up -d postgres
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ../../../shared
pip install -e ".[dev]"
cp .env.example .env
PYTHONPATH=backend/src python scripts/setup_db.py
./scripts/dev-backend.sh
```

In another shell:

```bash
cd frontend
npm install
npm run dev
```

Real runs require the Foundry/Azure OpenAI variables in `.env` and an identity
available through `DefaultAzureCredential`. Tests use a fake model and in-memory
checkpointer/audit repository:

```bash
pytest
cd frontend && npm install && npm test && npm run build
```

`./scripts/browser-e2e.sh` starts an in-memory fake-model backend plus Vite, runs
Playwright, and cleans up both processes. Install the Playwright Chromium binary once
with `cd frontend && npx playwright install chromium`.

Database setup uses the application virtual environment plus Psycopg; it does not
require a host `psql` executable. Application SQL is authoritative in
`backend/migrations/` and packaged in the wheel. Native saver migrations remain
framework-owned. Run explicit setup before serving, then use read-only verification:

```bash
PYTHONPATH=backend/src python scripts/setup_db.py
PYTHONPATH=backend/src python scripts/setup_db.py --verify-only
```

Set `TEST_DATABASE_URL` to a dedicated PostgreSQL database to run reconstruction,
durable-refund, and schema-isolation integration coverage.
Use fresh paired schemas instead of dropping application records while retaining
unrelated checkpoints. Runtime startup never applies DDL or silently selects a fake.

## API flow

1. `POST /api/cases` runs until terminal state or the durable approval interrupt.
2. `POST /api/cases/{case_id}/approval` records an explicit reviewer decision.
   The command is insert-once: an identical retry is accepted, while any changed
   checkpoint, decision, reviewer, or reason conflicts and cannot replace it.
3. `POST /api/cases/{case_id}/resume` supplies that decision through
   `Command(resume=...)`.
4. Read state, native audit history, or the additive SSE AG-UI projection.

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

See `observability/README.md`, `infra/README.md`, and `.foundry/README.md`.

## Independent Azure deployment

This lane now includes its own `azure.yaml`, Bicep, images, nginx configuration, and
deployment scripts. Nothing is shared with the MAF deployment.

- Local development and the FastAPI Container App remain on Python 3.12.
- The Foundry hosted agent uses direct-code `codeConfiguration` with
  `python_3_13` and the Responses `2.0.0` protocol.
- `infra/main.bicep` uses the resolved existing region and references the lane's
  Foundry account/project and model deployment. It manages ACR, Container Apps,
  PostgreSQL Flexible Server, Log Analytics, Application Insights, a project
  monitoring connection, identities and role assignments with reviewed update gates.
- The frontend is the only public Container App. nginx serves React and proxies
  `/api`, `/health`, and `/ready` to the internal FastAPI app.

The hosted adapter accepts either plain text (a `start` command) or safe JSON:

```json
{"action":"start","complaint":"I was charged twice.","customer_id":"customer-1"}
{"action":"approval","case_id":"case-id","checkpoint_id":"checkpoint-id","decision":"approve","reviewer_id":"reviewer-1"}
{"action":"resume","case_id":"case-id"}
```

Approval only records the durable command. Resume remains a separate explicit
operation. Responses contain case status, normalized outcome, and allowlisted event
summaries; they omit prompts, reasoning, workflow state, event data, tool payloads,
credentials, and checkpoint internals.

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

### Pre-cutover deployed baseline

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
[implementation ledger](../../../docs/design/issues-changes-fixes.md) for current gates.
