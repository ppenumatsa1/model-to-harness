# Double-charge workflow: LangGraph

An independent Python 3.12/FastAPI + React/Vite teaching app. It uses an idiomatic
`StateGraph`, conditional routes, parallel billing/policy branches, reducer-backed
evidence, bounded retry routes, and `interrupt()`/`Command(resume=...)` with a
PostgreSQL checkpointer. Application audit records live in separate
`langgraph_app.*` tables. Checkpointer migrations run through a psycopg connection
whose `search_path` is pinned to `langgraph_checkpoints`, so no saver table is created
in `public`; checkpoint internals are never exposed.

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

Database setup and reset use the application virtual environment plus Psycopg; they
do not require a host `psql` executable:

```bash
PYTHONPATH=backend/src python scripts/setup_db.py
PYTHONPATH=backend/src python scripts/reset_db.py
```

Set `TEST_DATABASE_URL` to a dedicated PostgreSQL database to run reconstruction,
durable-refund, and schema-isolation integration coverage.

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

Refund simulator results are persisted in `langgraph_app.refunds` before an uncertain
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
- `infra/main.bicep` defaults to `northcentralus` and creates the lane's Foundry
  account/project, `gpt-5.6-sol` `2026-07-09` GlobalStandard deployment, ACR,
  Container Apps, PostgreSQL Flexible Server, Log Analytics, Application Insights,
  a Foundry project monitoring connection, identities, and role assignments.
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

Before deployment, select an azd environment and provide the subscription. The
resource group must already exist:

```bash
export AZURE_SUBSCRIPTION_ID="<subscription-id>"
export AZURE_RESOURCE_GROUP="rg-model-harness"
export AZURE_LOCATION="northcentralus"
export POSTGRES_ADMINISTRATOR_PASSWORD="<strong-password>" # optional on the first run
./scripts/deploy_azure.sh
./scripts/smoke_azure.sh
```

`deploy_azure.sh` performs Azure operations and is intentionally not part of local
validation. It bootstraps resources, uses ACR remote builds (no local Docker
required), deploys release-specific image tags, prepares the self-contained hosted
source, and runs `azd deploy` only for this lane's hosted agent. When the PostgreSQL
password is omitted after the first deployment, the script reuses the value in the
selected azd environment rather than rotating it. Set `SMOKE_HOSTED_AGENT=1` when
running the smoke script to add a billable remote hosted-agent invocation.

### Current deployed environment

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

Application Insights now shows `foundry.responses.invoke` followed by
`workflow.run`, framework-local `workflow.node.*` spans, the model dependency, and
safe deterministic tool spans. Start, approval, and resume remain separate operations
linked by conversation, case, and run identifiers. Node and deterministic tool spans
are projected from durable audit timestamps; the real model dependency remains
auto-instrumented. Prompts, complaint text, checkpoint bodies, tool arguments/results,
and credentials are not recorded.
