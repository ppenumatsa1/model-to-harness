# MAF checkout-recovery harness

This is the first independent implementation of the checkout-recovery harness
contract. Microsoft Agent Framework provides the controlled agent loop,
context, tools, skills, and approval integration. PostgreSQL remains
authoritative for the checkout case, reviewer commands, remediation ledger,
audit history, and verification evidence.

The companion [checkout-recovery contract](../README.md) is
framework-neutral. This lane owns its own API, UI, telemetry, infrastructure,
tests, and Foundry Hosted Agent adapter.

## Run locally

Use Python 3.13, uv, Node.js, and a dedicated PostgreSQL database. For an existing
database, from this directory (for disposable local storage use the wrappers below):

```sh
uv sync --extra dev
export CHECKOUT_RECOVERY_DATABASE_URL='postgresql://<user>:<password>@localhost:5432/<database>'
uv run python scripts/migrate.py --apply
uv run uvicorn checkout_recovery_maf.main:create_app --factory --host 127.0.0.1 --port 8000
```

The default `scripted` development mode is explicitly offline. To exercise the actual harness,
set `CHECKOUT_RECOVERY_EXECUTION_MODE=maf`,
`CHECKOUT_RECOVERY_FOUNDRY_PROJECT_ENDPOINT`, and
`CHECKOUT_RECOVERY_FOUNDRY_MODEL_DEPLOYMENT`, and sign in to Azure before starting
the API. Production refuses scripted mode, missing PostgreSQL, or a missing API
token. Run the [frontend](frontend/README.md) separately; it proxies commands to
the API rather than asking the model to approve actions.

```sh
CHECKOUT_TEST_DATABASE_URL="$CHECKOUT_RECOVERY_DATABASE_URL" uv run pytest backend/tests
uv run python scripts/e2e.py --require-maf
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend exec playwright install chromium
npm --prefix frontend run test:e2e
```

The PostgreSQL test URL must identify a dedicated test database: tests create
synthetic cases but never drop or reset schemas. Migrations are versioned and
checksum-checked; neither the API nor Hosted Agent auto-migrates.

### Local PostgreSQL

This harness independently owns [compose.yaml](compose.yaml), project
`checkout-recovery-maf`, network `checkout-recovery-maf_default`, and volume
`checkout-recovery-maf_postgres-data`. It starts **only PostgreSQL 16** at
`127.0.0.1:35432`, database `checkout_recovery_local`, user `checkoutdev`.
There are no global container names, API/UI containers, or shared runtime helpers.
Both double-charge projects can run simultaneously. If this port is occupied,
startup fails rather than taking over another listener.

Create separate private settings once from this directory:

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

Exclusive creation protects existing settings. Never print resolved Compose
configuration, shell-source dotenv, or replace application/cloud `.env` files.
Do not export `POSTGRES_PASSWORD` or `COMPOSE_PROJECT_NAME` overrides. Preserve
`.env.compose`; changing it will not change an initialized volume's password.

The harness-owned wrapper validates the Compose project and loopback port, then
provides canonical local `DATABASE_URL`, explicitly mapped to this harness's
existing `CHECKOUT_RECOVERY_DATABASE_URL` and `CHECKOUT_TEST_DATABASE_URL` contracts.
Only the child process is changed; private Azure configuration is untouched.
The wrapper selects offline `scripted` development mode and disables exporters.

```bash
uv sync --extra dev
.venv/bin/python scripts/with_local_db.py -- .venv/bin/python scripts/migrate.py --apply
.venv/bin/python scripts/with_local_db.py -- .venv/bin/python -m pytest backend/tests
# Optional separate offline API; do not replace the existing double-charge previews.
.venv/bin/python scripts/with_local_db.py -- .venv/bin/python -m uvicorn checkout_recovery_maf.main:create_app --factory --host 127.0.0.1 --port 18020
```

These PostgreSQL tests use deterministic/fake investigators, not a cloud model.
They retain synthetic records only in the new local database. Use this wrapper
for every local command; unwrapped commands retain existing process configuration.

```bash
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose stop postgres
docker compose --env-file .env.compose start --wait postgres
```

Stop/start preserves persisted cases without affecting other projects.
`down` retains the volume; never use `down -v` or prune volumes. The retired root
Compose data is not reused or deleted. Root `shared/` stays framework-neutral
and unchanged.

## Delivery

### Backend boundaries

`config.py` owns settings and fail-closed validation. `bootstrap.py` constructs
the checkout-owned synchronous runtime, shared only by this lane's API and
Hosted adapter. `main.py` exports the API factory; importing it creates no app,
database pool, investigator, or telemetry exporter. `api/app.py` owns lifespan
and authentication, `api/dependencies.py` resolves the active service, and
`api/routers/` contains explicit case commands, safe queries, and health checks.
Safe query projection assembly belongs to the application service; projections
remain pure and the original domain reads remain available internally.

The lifespan constructs and opens resources only when started and closes owned
resources on shutdown or startup failure. Injected services retain ownership of
their repositories and investigators; no unused replacements are constructed.
Hosted calls the same runtime via `asyncio.to_thread`, requires PostgreSQL and
MAF, and never initializes API telemetry or requires the API proxy token.
The Responses SDK remains the owner of Hosted telemetry and message capture
stays disabled. Neither host changes synchronous transactions, approval
binding, idempotency, framework state ownership, or browser-safe projections.

`azure.yaml` provisions the independent Foundry project/model and directly
packages the Python Responses 2.0 Hosted Agent. `infra/app/main.bicep` owns the
ACR, PostgreSQL, monitoring, managed identities, and Container Apps. It deploys
foundation resources first and application images second.

`scripts/release.py` provides `prepare`, `preview`, `foundation`, `configure`,
`migrate`, `apps`, `e2e`, `browser`, and `evidence` steps. Select the azd environment
explicitly. `prepare` accepts `--operator-ip`; `apps` accepts immutable
`--backend-image` and `--frontend-image` references. Inspect the IaC preview
before creating resources. The application release and Hosted Agent deployment
are separate commands; both use the same canonical backend source.

For a refactor of the **existing** environment, do not rerun `foundation` or the
broader `apps` template. Build API/UI images from the clean reviewed commit,
using unique `<full-commit>-<release-id>` tags, then resolve their digests.
The image-only path requires a saved preview and refuses source, image or
configuration drift between preview and apply:

```bash
uv run python scripts/release.py update-existing --environment crmaf-20260912 \
  --source-commit <full-commit> --backend-image <registry/repository@sha256:digest> \
  --frontend-image <registry/repository@sha256:digest> --output-dir <fresh-private-directory>
# Repeat exactly the same arguments with --apply after reviewing the preview.
```

This path locks both tags and manifests and verifies both live revisions at
completion. It does not change secrets, networking, identities, monitoring
connections or migrations. It is not an atomic two-app transaction: a failed
partial rollout retains its receipt for explicit reconciliation, not blind retry.
Deploy the Hosted service separately with the same committed canonical source.
For fresh acceptance, use `e2e --output-dir <directory>` followed by
`evidence --output-dir <directory> --hosted-report <actual-version-report.json>`;
the evidence step never assumes Hosted version 2. Hosted validation supports
`scripts/verify_hosted.py --smoke` before the full seven-scenario matrix.

Private generated values live in `.azure/<environment>/release-secrets.json`
and `release.parameters.json`, with mode 0600. The former contains the UI login
and API/database secrets; never commit or print it. Nginx authenticates the UI,
injects the private API token server-side, and verifies TLS to the private API.
It listens on **8080**, including the unauthenticated `/healthz` probe.

The verified environment is `crmaf-20260912`, resource group
`rg-crmaf-20260912`, region `northcentralus`. Its Hosted Agent is
`checkout-recovery-maf:2`. The UI is
<https://crmaf-q35uqmuqoh7co-web.icymoss-074cbdaa.northcentralus.azurecontainerapps.io>.
See the [delivery ledger](docs/issues-changes-fixes.md) for evidence, image
digests, evaluation results, and the remaining production-hardening boundary.

## Foundry evaluation

Run `uv run python scripts/prepare_evals.py` and
`uv run python scripts/verify_evals.py` to materialize and check the seven
start-command cases. Register the deterministic grader and create its native
evaluation group:

```sh
uv run python scripts/register_native_evaluation.py \
  --project-endpoint "$CHECKOUT_RECOVERY_FOUNDRY_PROJECT_ENDPOINT"
```

Submit the generated `.foundry/datasets/checkout-start-contract.jsonl` rows with
Foundry's agent-target batch evaluation tool, using the returned `evaluationId`,
`evaluatorNames=["checkout_exact_contract"]`, and an explicit agent version.
The dataset is beneath `infra/foundry-hosted/agent/`. Reuse the native group;
do not substitute a model-completion run or an LLM prompt judge.
Then inspect every result, not just the job status:

```sh
uv run python scripts/collect_evaluation.py \
  --project-endpoint "$CHECKOUT_RECOVERY_FOUNDRY_PROJECT_ENDPOINT" \
  --environment <environment> --eval-id <evaluation-id> --run-id <run-id>
```

The accepted run and catalog version are recorded in the agent's
`.foundry/agent-metadata.yaml`. It passed all seven start contracts; consequential
cases remain durably paused. The separate command E2E gate performs explicit
approval and resume. Legacy `register_evaluator.py` reproduces an unresolved
supplemental prompt-judge experiment and is not the accepted release path.

## What this example proves

The model can vary its diagnostic tool sequence, but cannot issue business
writes. A separate deterministic policy controls remediation and approval.
PostgreSQL transactions serialize each case's commands across replicas;
matching retries recover the recorded result. MAF session/workspace data lives
in a separate framework-owned table and is not the source of approval authority.

`scripts/verify_hosted.py` and `scripts/e2e.py` compare every normalized outcome
field. `scripts/verify_business.py` re-reads persisted cases, remediation results,
intent records, approvals, sessions, and audit events. The cloud evaluation
is supplemental: `scripts/collect_evaluation.py` requires both its native grader result
and an independent exact JSON-contract comparison for every item.

This remains a synthetic educational application, not a production payment
integration. Reviewer identity is supplied through an authenticated demo
boundary, not independently verified Entra reviewer claims. The database uses
password authentication and an Azure-services firewall exception. Real downstream
systems need their own authorization, idempotency, reconciliation, and tighter
network/identity controls before use with customer data.
