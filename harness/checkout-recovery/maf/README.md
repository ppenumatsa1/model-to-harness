# MAF checkout-recovery harness

This is the first independent implementation of the checkout-recovery harness
contract. Microsoft Agent Framework provides the controlled agent loop,
context, tools, skills, and approval integration. PostgreSQL remains
authoritative for the checkout case, reviewer commands, remediation ledger,
audit history, and verification evidence.

The companion [checkout-recovery contract](../docs/README.md) is
framework-neutral. This lane owns its own API, UI, telemetry, infrastructure,
tests, and Foundry Hosted Agent adapter.

## Run locally

Use Python 3.13, uv, Node.js, and a dedicated PostgreSQL database. From this directory:

```sh
uv sync --extra dev
export CHECKOUT_RECOVERY_DATABASE_URL='postgresql://<user>:<password>@localhost:5432/<database>'
uv run python scripts/migrate.py --apply
uv run uvicorn checkout_recovery_maf.bootstrap:app --host 127.0.0.1 --port 8000
```

The default `scripted` mode is explicitly offline. To exercise the actual harness,
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

## Delivery

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
