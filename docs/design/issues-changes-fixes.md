# Issues, changes, and fixes

This is a concise implementation ledger, not a release history.

## Initial implementation

- Added a framework-neutral Python 3.12 shared package with Pydantic contracts,
  deterministic billing/policy/approval simulators, fixtures, evaluation contracts,
  and idempotency tests.
- Added independent MAF and LangGraph FastAPI/React applications with native workflow
  control, PostgreSQL persistence, durable events, approval pause/resume, AG-UI
  projections, selected-run explanations, tests, evaluations, and local scripts.
- Added one root PostgreSQL Compose dependency while leaving schema migrations and
  repository code inside each application.
- Consolidated implementation documentation into the canonical `docs/design/` set.

## Important fixes and safeguards

- Refund IDs and timestamps are deterministic, and refund storage is atomically keyed
  by idempotency key.
- An uncertain response after refund storage can be retried without creating a second
  refund; each app persists a request fingerprint and refund ID for reconstruction.
- Conflicting approval decisions and idempotency-key reuse are rejected.
- LangGraph application audit tables and native checkpointer tables use separate
  schemas; MAF checkpoint and audit records remain in its application-owned schema.
- AG-UI tool results use explicit result/end events. CopilotKit discovers and invokes
  a real read-only `selected-run` runtime; consequential commands remain explicit API
  calls and are not exposed as assistant tools.
- LangGraph database initialization uses Python and Psycopg, so a host `psql`
  executable is not an undeclared prerequisite.

## Known validation limitations

- Shared package tests and documentation-link checks run without external services.
- Compose syntax can be checked statically, but Docker was unavailable in the current
  validation environment. PostgreSQL reconstruction tests are included and wired to
  the independent CI workflows through `TEST_DATABASE_URL`, but were skipped locally.
- Model-backed smoke runs require caller-supplied Foundry configuration and identity;
  no cloud credentials or resource values are stored in the repository.
- Browser end-to-end suites require the framework-local frontend dependencies and
  Playwright browser installation.

See each application README for its current validation commands.

## 2026-09-01 - Copilot CLI heap exhaustion during broad repository discovery

- A generated Node.js diagnostic report recorded
  `Allocation failed - JavaScript heap out of memory` in the Copilot CLI process.
- The process reached about 6.1 GiB resident memory and 6.3 GiB peak resident
  memory. The report contained no JavaScript stack and no environment-variable
  values, so it did not identify an application defect or expose deployment
  credentials.
- Broad recursive file discovery was replaced with lane-scoped and directory-scoped
  reads. Generated `report.*.json` files are ignored because they are local tool
  diagnostics, not repository artifacts.

## 2026-09-01 - First MAF ACR build failed on shared-package license metadata

- The first remote backend image build failed because `shared/pyproject.toml`
  references the repository-level `LICENSE`, but the container build copied only
  `shared/` and the MAF lane.
- The backend image now copies the root license into `/workspace/LICENSE` before
  package installation.
- A root `.dockerignore` now excludes Git metadata, vendored skills, virtual
  environments, frontend dependencies, build output, caches, and diagnostic reports.
  This also prevents multi-hundred-megabyte local dependency trees from being sent to
  Azure Container Registry builds.

## 2026-09-01 - MAF hosted local smoke exposed checkpoint enum allowlisting

- The first local Responses-protocol invocation completed the business graph but
  failed while reloading its final PostgreSQL checkpoint because the MAF checkpoint
  codec blocked the `RunStatus` enum during safe deserialization.
- The checkpoint allowlist now includes the workflow's status and approval enums,
  while retaining restricted deserialization rather than weakening the codec.
- A focused codec regression test covers the terminal `RunStatus` round trip.
- The first remote approval/resume attempt then exposed the timezone object embedded
  in the durable `ApprovalResponse.decided_at` value. The restricted allowlist now
  includes only Pydantic Core's `TzInfo`, with a dedicated approval timestamp
  round-trip test.

## 2026-09-01 - MAF frontend proxy returned 502 against internal Container App

- Both Container App revisions were healthy, and the FastAPI readiness probes
  succeeded, but nginx logged an SSL-handshake reset while proxying to the internal
  backend ingress.
- Azure Container Apps internal ingress requires the backend FQDN as TLS SNI.
  The nginx proxy now enables `proxy_ssl_server_name` and sets `proxy_ssl_name` to
  the internal backend hostname for both API and health routes.
- Azure Resource Health and AppLens do not currently support Container Apps in the
  available diagnostic tools, so revision state and container logs were used as the
  authoritative evidence.

## 2026-09-01 - Foundry evaluation required built-in evaluator prefixes

- The first hosted MAF evaluation request was rejected because
  `task_completion` was interpreted as a project evaluator name.
- Current Foundry evaluation APIs require the `builtin.` prefix for Microsoft
  evaluators. The hosted suite now uses `builtin.task_completion` and
  `builtin.relevance`.
- The next run reached `Completed` but both rows errored because the current
  evaluation target template reads `item.query`; the initial dataset used the older
  `input` field. Hosted evaluation datasets now use `query`.
- After that correction, the ordinary completed case passed while an intentional
  approval pause was scored as incomplete by generic task-completion evaluators.
  Durable HITL remains covered by the framework-specific deterministic evaluation;
  the generic hosted smoke suite now uses completed, non-HITL cases.

## 2026-09-01 - LangGraph deployment review found rerun-safety gaps

- The first LangGraph Azure scaffold generated a new PostgreSQL administrator
  password whenever the deployment script ran without an explicitly supplied
  password. Re-provisioning with a different value could rotate the server password
  while existing application configuration still referenced the previous value.
- The scaffold also used mutable `latest` image tags for both Container Apps. A
  successful ACR build would therefore not provide an immutable release reference or
  clearly communicate which image revision was deployed.
- The deployment script will be corrected to reuse a persisted secret on reruns and
  publish release-specific image tags before live provisioning.
- The hosted source passed its local adapter, backend, frontend, lint, packaging, and
  Bicep checks, but it did not yet include a Foundry-hosted evaluation suite. A
  lane-owned `eval.yaml` and completed non-HITL smoke dataset will be added before the
  hosted deployment is considered complete.

## 2026-09-01 - LangGraph deployment launcher assumed a `python` command

- The first live deployment attempt stopped during its prerequisite check because
  the host provides Python through `python3` rather than an unversioned `python`
  executable. No Azure resources had been changed at that point.
- The deployment script now uses a configurable `PYTHON_BIN`, defaulting to
  `python3`, for password generation and hosted-source preparation.

## 2026-09-01 - Uppercase Bicep output names were normalized unexpectedly

- The first LangGraph infrastructure deployment succeeded, but the deployment script
  read empty ACR and Foundry values because ARM exposed output keys beginning with
  `AZURE` using an unexpectedly normalized `azurE` prefix.
- The empty registry value caused `az acr build` to reject the registry name before
  either application image was built.
- Lane outputs now use conventional lower-camel-case names, and the deployment script
  reads those stable keys before starting image builds or hosted-agent deployment.

## 2026-09-01 - LangGraph ACR builds used the wrong Dockerfile base directory

- After infrastructure provisioning, the first image-build attempt could not locate
  the backend Dockerfile. The script changes into the LangGraph lane but supplied a
  repository-relative Dockerfile path, effectively duplicating the lane path.
- ACR build commands now use resolved absolute Dockerfile paths while retaining the
  repository root as the build context required by the shared package.

## 2026-09-02 - Failed azd secret lookup was captured as a database password

- LangGraph Hosted Agent version 1 became active, but post-deployment inspection
  found that its `DATABASE_URL` contained azd's `key not found` diagnostic instead of
  a PostgreSQL password.
- The deployment script used command substitution followed by `|| true`; azd emitted
  its failure text on standard output, so the non-empty diagnostic was mistaken for
  an existing secret and was also supplied to the infrastructure deployment.
- Secret reuse now assigns the result only when `azd env get-value` exits
  successfully. A missing key generates and persists one valid credential before
  infrastructure, Container Apps, and the Hosted Agent are deployed.
- Hosted Agent version 1 must not be treated as a valid release. The corrected
  deployment rotates PostgreSQL to the valid persisted credential and creates a new
  agent version before workflow verification.

## 2026-09-02 - Azure Monitor exporter logs created a telemetry feedback loop

- After the credential repair, the React revision was healthy but the FastAPI
  revision remained in `Activating`. Console logs showed one Application Insights
  export request and success message every second, with no Uvicorn startup message.
- Root structured logging was configured at `INFO` before the Azure Monitor distro.
  The distro captured its own exporter and Azure SDK HTTP transport logs, then each
  export generated more logs to export.
- The LangGraph observability setup now raises only the Azure Monitor exporter and
  Azure SDK HTTP transport logger thresholds to `WARNING` after instrumentation.
  Application and workflow logs remain at the configured level.
- A regression test verifies that instrumentation is configured and the two internal
  telemetry logger families cannot re-enter the exported application log stream.

## 2026-09-02 - PostgreSQL schema formatting treated JSON defaults as placeholders

- Once telemetry startup progressed normally, the FastAPI revision failed during
  PostgreSQL schema creation with `IndexError: tuple index out of range`.
- `PostgresAuditRepository` safely inserts its schema identifier with
  `psycopg.sql.SQL.format()`, but two `DEFAULT '{}'::jsonb` literals were not escaped.
  Psycopg therefore interpreted each empty JSON object as another format placeholder.
- The SQL templates now use `DEFAULT '{{}}'::jsonb`, which renders the intended
  literal JSON object after the schema identifier is composed.
- This defect was hidden by in-memory tests and the locally skipped PostgreSQL
  integration suite, reinforcing that deployment acceptance must include startup
  against an actual PostgreSQL database.

## 2026-09-02 - LangGraph Azure smoke script also assumed `python`

- The first public application smoke reached the deployed service but stopped before
  exercising the workflow because the smoke script invoked an unversioned `python`
  executable unavailable on the release host.
- Like the deployment script, the smoke script now uses configurable `PYTHON_BIN`
  with a `python3` default.

## 2026-09-02 - Model defaults and Hosted Agent RBAC blocked live inference

- The first public workflow request reached the real model but `gpt-5.6-sol`
  rejected the explicit `temperature=0.0`; this model supports only its default
  temperature. Model configuration now omits the parameter by default and forwards
  it only when explicitly configured.
- Hosted Agent version 4 acquired a managed-identity token but received HTTP 401 from
  the model deployment. The Container App identity already had the required role,
  but the Hosted Agent instance identity is created only during agent deployment and
  therefore was not available to the initial Bicep role assignments.
- After each hosted deployment, the lane script now reads the deployed instance
  identity and idempotently grants it `Cognitive Services OpenAI User` on this lane's
  Foundry account. No sibling identity or shared deployment role is used.
- Hosted code deployment also exposes a managed-agent blueprint identity, but Azure
  rejects RBAC assignments to that specialized principal type. Model RBAC therefore
  remains attached only to the agent instance identity; hosted smoke tests must allow
  normal role-propagation time before diagnosing identity selection.
- After propagation, Hosted Agent version 5 completed an ordinary remote case and a
  three-command durable HITL flow. The retry-safe scenario stored a refund before an
  intentionally uncertain response, retried with the same idempotency key, and
  verified exactly one durable refund before notification.

## 2026-09-02 - Final Azure verification

- The LangGraph public React/nginx application and same-origin FastAPI proxy passed
  readiness and durable start/approval/resume smoke tests.
- LangGraph Hosted Agent version 5 passed both an ordinary no-duplicate invocation
  and a three-command retry-safe refund flow. PostgreSQL confirmed one ledger row and
  one distinct refund ID for that case.
- LangGraph Foundry evaluation
  `eval_096328c4eb50463caa4cd667a36843c3`, run
  `evalrun_a888c01543a34d4c80b321ccf26e29a2`, completed with 2 passed, 0 failed,
  and 0 errored rows.
- LangGraph Application Insights contained 1,723 recent traces with no
  severity-level errors in the final query window, including explicit approval and
  exactly-one-refund verification messages.
- MAF Hosted Agent version 2 remained active, its public proxy smoke passed, and its
  Application Insights workspace reported 141 traces with no severity-level errors
  in the final 24-hour query.

## 2026-09-02 - MAF deployment automation was reconciled after live rollout

- The original MAF script generated a new PostgreSQL password on every invocation,
  used mutable `latest` image tags, assumed an unversioned `python` executable, and
  supplied repository-relative Dockerfile paths after changing into the lane.
- It now selects the explicit MAF azd environment, reuses the persisted database
  credential, generates one only when absent, uses configurable `PYTHON_BIN`,
  resolves Dockerfiles from the lane root, and deploys release-specific image tags.
- The already-running MAF environment was not rebuilt solely for this script cleanup;
  its public smoke, Hosted Agent status, telemetry, and durable ledger were verified
  independently.
