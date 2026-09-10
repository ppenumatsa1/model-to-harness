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

## Initial validation limitations (historical)

These describe the initial implementation, not the latest MAF cutover checks below.

- Shared package tests and documentation-link checks run without external services.
- Compose syntax was checked statically, but Docker was unavailable in the initial
  validation environment. PostgreSQL reconstruction tests were included and wired to
  the independent CI workflows through `TEST_DATABASE_URL`, but were skipped then.
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

## 2026-09-02 - Foundry projects had telemetry resources but no monitoring connections

- Both lanes created Application Insights and exported selected telemetry, but the
  Foundry project connection lists were empty. Hosted monitoring therefore depended
  on manually supplied environment values and Foundry could not consistently surface
  project conversations and transaction traces.
- Each independent Bicep template now creates an `ApplicationInsights` project
  connection targeting that lane's component and grants the project identity Log
  Analytics Reader access to both Application Insights and its workspace.
- Hosted `azure.yaml` files no longer attempt to set the platform-reserved
  `APPLICATIONINSIGHTS_CONNECTION_STRING`. Foundry injects it from project monitoring;
  the Container App backends continue to receive their lane-owned connection strings
  through Container App secrets.
- Azure verification confirmed one `AppInsights` connected resource in each project,
  targeting only the matching lane resource.

## 2026-09-02 - LangGraph needed an explicit Responses-to-workflow trace hierarchy

- The baseline LangGraph resource contained logs under `unknown_service`, but no
  cohesive hosted request, workflow, node, model, or conversation hierarchy. MAF
  already emitted its framework-native workflow/edge/executor hierarchy.
- The LangGraph Responses handler now creates `foundry.responses.invoke` with safe
  GenAI agent, response, and conversation attributes. The command service creates
  `workflow.run` and attaches case/run correlation.
- A trial of the preview `langchain-azure-ai` callback traced ordinary graph nodes but
  emitted missing `on_interrupt` and `on_resume` callback warnings and omitted parts
  of the resumed retry path. It was removed rather than retained as a fragile runtime
  dependency.
- LangGraph now projects `workflow.node.*` and deterministic tool spans from its
  durable PostgreSQL audit timestamps after each graph command. The model client's
  real dependency span remains under the same `workflow.run`. The projection
  records only identifiers, node/tool/model names, counts, and source metadata; it
  never records prompts, complaint text, raw state, checkpoint bodies, credentials,
  idempotency keys, or tool arguments/results.
- This projection is operational telemetry, not a replacement for the native audit.
  Start, approval, and resume remain separate request traces linked by conversation,
  case, and run identifiers.

## 2026-09-02 - Trace deployment and verification

- MAF Hosted Agent version 3 and LangGraph Hosted Agent version 13 are active.
- Fresh no-duplicate, approval-denied, and retry-safe-refund scenarios were exercised
  with separate durable approval and resume commands. Both retry-safe flows completed
  with one verified refund.
- MAF trace `d75d9e816211ea239f3a31f077faef34` contains the hosted request plus
  `workflow.run`, edge-group, executor, model, and message-send dependencies with the
  same conversation key.
- LangGraph version-12 trace `b8a81ebbf2c277c001311545c1f160d6`
  contains `foundry.responses.invoke` → `workflow.run` → approval, refund,
  verification, notification, one real model dependency, and safe tool dependencies
  under one operation ID with conversation, case, and run correlation.
- LangGraph version-13 trace `8f0c52b318c7eee4761407ab00a5be25`
  confirms the outer `foundry.responses.invoke` span now carries the nested command
  result's case ID, run ID, terminal status, current step, and conversation
  correlation.
- The public LangGraph React/nginx/FastAPI path passed a fresh durable
  start/approval/resume smoke after the backend telemetry revision became healthy.

## 2026-09-02 - Final telemetry review closed correlation and redaction gaps

- The LangGraph Responses wrapper initially looked for case and run fields at the
  command result root, while successful results place them inside the allowlisted
  `case` object. The wrapper now reads that object before applying workflow span
  attributes.
- The wrapper no longer calls `record_exception` or logs raw stack traces. Validation
  exceptions can contain rejected complaint or command values, so traces now record
  only the exception class and sanitized error code.
- Lane agent instructions use the standard uppercase `AGENTS.md` convention. Both
  files now document independence, durable
  approval, PostgreSQL authority, Foundry packaging, telemetry safety, and required
  validation commands.

## 2026-09-10 - MAF direct-cutover implementation and verification status

- Work is on `refactor/maf-backend-cutover`, based on the local `e1299ba` checkpoint.
  Source has passed local acceptance and independent review. Nothing has been pushed,
  merged, or deployed during this cutover. `main` is unchanged.
- Replaced the flat MAF backend with application, native MAF workflow/executor,
  persistence, API, projection, and explicit testing boundaries. Removed superseded
  root modules rather than retaining compatibility shims or old checkpoint readers.
  LangGraph and shared runtime code remain unchanged.
- `backend/migrations/` is now authoritative: version/checksum tracking, transactional
  advisory locking, repeatable application, a locked `--require-empty` release guard,
  and rejection of unversioned legacy storage. Runtime startup validates schema
  readiness without migrating or resetting it.
- Integrated explicit API/hosted runtime lifecycle, safe telemetry/provider ownership,
  packaged SQL, release harnesses, independent hosted dependencies, and publication
  links. Native approval remains a separate persisted command before resume.

| Completed check | Evidence |
| --- | --- |
| Backend/shared integration | Final consolidated suite: 200 tests passed, including real PostgreSQL migrations, checkpoint reconstruction, refund invariants, CI/feed contracts, and telemetry tests; Ruff passed |
| Deterministic evaluations | All seven fixture scenarios passed |
| Frontend | Four unit tests, production build, container build, and nginx entrypoint/configuration check passed |
| Local API/browser | Final real-model PostgreSQL-backed smoke, all seven command scenarios, and browser approval/resume/outcome/CopilotKit flow passed |
| Installed wheels | SQL migration apply/repeat and all seven evaluations passed outside the checkout with locked dependencies |
| Python 3.13 hosted package | Final declared SDK dependencies, common logging startup without Uvicorn, import/resources, compatibility checks, and all seven real-model Responses command scenarios passed |
| Real model and restart | Production API smoke passed; real hosted Responses start and approval paused durably, then a fresh server process resumed to a verified refund also visible through the API |

- Integration fixes included explicit MAF pytest configuration when combining shared
  tests, repository-backed in-memory checkpoint views, isolated telemetry test log
  levels, current browser selectors, and unique browser case/idempotency identifiers.
- **Pending:** Azure IaC preview
  and rollout; deployed smoke, API/browser/hosted E2E, actual new-version Foundry
  evaluation results, and observed Application Insights ingestion.
- Read-only Azure discovery found the existing MAF PostgreSQL server stopped. After
  local/review gates, the authorized rollout must explicitly start it, wait for
  readiness, and use the fresh MAF-only schema. No Azure resource mutations have
  occurred during this cutover.
- Next sequence: resolve package downloads, finish/review release artifacts, rerun
  affected local gates, commit the validated feature-branch source, preview/apply the
  MAF-only release, and verify actual cloud behavior before the merge handoff.
- **Current distance to deployment:** local acceptance and targeted review are
  complete; the next step is the reviewed Azure rollout. Both images now build, and common logging
  starts correctly in the isolated hosted environment. Hosted client pins and
  supplied-ID correlation are implemented. Real-model local execution is not a
  substitute for testing a newly deployed Foundry-hosted version; that cloud
  verification is still pending.

## 2026-09-10 - Container package downloads require approved package feeds

- Both backend and frontend image builds failed during package downloads:
  Python downloads from `files.pythonhosted.org` and npm tarballs from
  `registry.npmjs.org` returned TLS handshake failures inside containers. Host
  downloads succeeded; using Docker host networking did not resolve the failure.
  This is a package-download environment blocker, not a workflow test failure.
- The user supplied these approved repository feeds:

| Ecosystem | Approved feed |
| --- | --- |
| npm | `https://packagefeedproxy.microsoft.io/npm/` |
| PyPI | `https://packagefeedproxy.microsoft.io/pypi/simple/` |
| NuGet | `https://packagefeedproxy.microsoft.io/nuget/v3/index.json` |

- Container probes reached the npm and PyPI mirrors successfully, including an actual
  npm tarball download. The MAF frontend
  now declares its registry in `.npmrc`, copied before Docker's `npm ci`; the MAF
  Python project declares the approved default uv index. Its lockfile now uses that
  index with all 105 package versions unchanged; feed/workspace contracts passed.
  The frontend image rebuilt successfully through the mirror, and its actual nginx
  entrypoint/configuration check passed. This closes the frontend download blocker.
  The backend image also built successfully and passed all seven evaluations plus
  packaged SQL/tested-SDK checks inside the image. Hosted requirements now explicitly
  select the approved PyPI index. Package-download blockers are resolved.
- NuGet is recorded for future applicable work; this MAF lane has no NuGet
  installation step, so no unused .NET configuration is added.
- TLS verification remained enabled throughout; no certificate or transport safety
  checks were disabled.

## 2026-09-10 - Independent MAF review found CI and access-logging regressions

- The independent review reproduced two release blockers despite the passing local
  suite. No Azure rollout occurred.
- **CI database mismatch:** the workflow still provisioned the original database
  and port, while the integration fixture intentionally accepts only the dedicated
  `mafdev` / `maf_cutover_tests` database at `127.0.0.1:5434`. CI service settings,
  health checks, and URLs are now aligned; a contract invokes the actual fixture
  guard using CI configuration. The local test setup is documented in the MAF README.
  The remote-database restriction is retained. The CI contract and complete
  PostgreSQL integration directory passed 27 tests; lint and whitespace checks passed.
- **Uvicorn access logging:** safe log filtering cleared the argument tuple required
  by Uvicorn's access formatter, causing logging tracebacks on requests. A safe JSON
  formatter and three real-Uvicorn regressions now retain only allowlisted
  method/status and correlation fields; the full suite passed 192 tests.
- Isolated Python 3.13 startup then caught an API-only `uvicorn` import introduced
  by that fix: the hosted server uses Hypercorn and does not depend on Uvicorn.
  Formatter detection now checks already-loaded classes without importing Uvicorn,
  including subclasses. Isolated hosted logging startup passed with Uvicorn absent.
  The actual restarted Uvicorn API retained method/status, omitted a sensitive query
  sentinel, and produced no logging traceback. The isolated hosted CI gate now
  executes common logging setup, not just imports, to catch startup regressions.
- Both fixes passed focused verification and independent follow-up before Azure rollout.
- The independent follow-up confirmed both original findings resolved, with no
  additional release/packaging blockers. A final narrow hosted refinement loads
  authoritative case/run state before approval/resume correlation; its two new
  contracts pass, and the consolidated suite now passes 200 tests. The reviewer also
  examined that final refinement and found no blocker.

## 2026-09-10 - Browser acceptance assumed the fake model's exact wording

- Final real-model API smoke and all seven command scenarios passed, but browser
  acceptance required the literal fake-model phrase `Current status is`. The real
  model returned an accurate explanation using different wording.
- The browser test now verifies successful CopilotKit/AG-UI completion, a nonempty
  streamed explanation, and exact rendering of that returned explanation. It reuses
  the existing SSE parser and still checks the authoritative outcome, absence of
  assistant errors, and that no direct assistant command path was used.
- Production UI and model behavior are unchanged. Business-result assertions remain
  deterministic; model wording is not treated as a fixed UI contract. The corrected
  real-model browser run passed, including refund completion, selected-run explanation,
  and switching to a no-duplicate case.
