# Microsoft Agent Framework double-charge app

This independent Python 3.12 + React teaching app turns a deterministic
double-charge support scenario into an inspectable, durable workflow. Microsoft
Agent Framework (MAF) owns the explicit graph, fan-out/fan-in, status events, and
checkpoint resume. PostgreSQL owns application state, selected memory, approvals,
MAF checkpoints, the idempotent refund ledger, outcomes, and append-only audit events.

## What the example teaches

- Explicit nodes and conditional edges rather than a hidden agent loop.
- Parallel billing and refund-policy validation with a synchronized join.
- A durable approval pause: `POST /approval` records a command and `POST /resume`
  separately resumes the saved MAF checkpoint.
- Bounded retries plus explicit failure and manual-review routes.
- A PostgreSQL-durable refund ledger with stable idempotency keys, request
  fingerprint conflict detection, and exactly-once verification after restart.
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
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e "../../../shared"
python -m pip install -e ".[dev]"
cp .env.example .env
```

The root shared package is deliberately installed separately. It owns only the
framework-neutral domain, fixtures, evaluation contracts, and deterministic
simulators. This app never imports LangGraph or another app's code.

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
.venv/bin/ruff check backend
.venv/bin/pytest
.venv/bin/python evals/run.py
npm --prefix frontend test
npm --prefix frontend run build
```

With the API running:

```bash
.venv/bin/python scripts/smoke.py
.venv/bin/python scripts/e2e.py
./scripts/e2e-browser.sh
```

See `observability/README.md`, `infra/README.md`, and `.foundry/README.md` for
operational boundaries and safe future-hosting placeholders.

## Deployed teaching environment

- Public application:
  <https://mth-maf-wh2su65huqw5o-web.livelyhill-0f2b68f2.northcentralus.azurecontainerapps.io>
- Foundry project: `model-harness-maf`
- Hosted Agent: `model-harness-maf` version 3
- Model: `gpt-5.6-sol` version `2026-07-09`, Global Standard
- Region/resource group: `northcentralus` / `rg-model-harness`
- Hosted evaluation: 2 passed, 0 failed, 0 errored

Remote testing completed an ordinary case and a separate start, approval, and resume
sequence. PostgreSQL contains one durable refund for the verified idempotency key.
The deployment is educational and is not a production network or payment-system
reference.

The Foundry project is connected through IaC to the lane-owned Application Insights
resource. Hosted Responses traces preserve MAF's native `workflow.run`,
edge-group, executor, model, and message-send hierarchy and include conversation
correlation across separate approval and resume requests.
