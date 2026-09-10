# Issues, changes, and fixes

This is a concise implementation ledger, not a release history.

## LangGraph direct cutover - implementation in progress

### Current progress checkpoint

**Ten of thirteen work packages are complete; corrective hosted deployment and
cloud acceptance are active, and final handoff is pending.** Implementation is committed locally as
`a27cb6e`, with subsequent release/startup corrections through `901634a`, on
`refactor/maf-backend-cutover`; no push or merge occurred.

| Area | Current evidence / remaining work | Status |
| --- | --- | --- |
| Backend and storage cutover | Independent package boundaries, explicit application/native-checkpoint setup, verify-only startup, durable approval/resume and recovery are implemented. No legacy-data migration. | Complete |
| Independent review | The checkpoint-evidence restart defect is fixed and covered at both pre-validation restart boundaries; reviewer finding closed. | Complete |
| Local acceptance | 182 tests with PostgreSQL and no skips; seven deterministic evaluations and seven API scenarios; frontend tests/build/browser; wheel and isolated Python 3.13 hosted package gates passed. | Complete |
| Telemetry implementation | Real execution spans, safe correlation, full-retention policy and KQL positive/negative gates are implemented and locally checked. Fresh deployed hierarchy, noise and privacy still need verification. | Local complete; cloud pending |
| Existing infrastructure | Corrected API revision `0000014` and frontend revision `0000009` are ready on immutable `901634a` images. Foundry version 14 is active; runtime, environment and downloaded source archive are verified. | Deployed |
| Release gate | Strict app-only previews and immutable rollout checks passed. Recovery verified existing cutover storage read-only. Corrective hosted resource-lifecycle/transport edits are now in the worktree, not yet validated or deployed. | Corrective release active |
| Cloud acceptance and handoff | Seven API scenarios, direct SQL evidence, browser approval/resume, hosted v14 smoke and all four cloud evaluation items passed. Both full hosted matrix attempts stopped after four scenarios. Final hosted E2E, ancestry/noise/privacy proof and evidence sync remain. | Active; not complete |

Core implementation has stopped and its owned test resources were cleaned up.
Parent-owned disposable PostgreSQL was also removed after acceptance. MAF runtime,
shared package and deployed MAF resources remain unchanged.

### Partial rollout: API startup blocks revision readiness

The `d6b0d09` release passed explicit fresh storage setup and ARM deployment, then
timed out waiting for the latest API revision to become ready. Read-only checks
confirmed the intended backend/frontend image digests are configured, frontend
revision `0000008` is ready, and API revision `0000013` has
`ActivationFailed` / `Deployment Progress Deadline Exceeded`. Platform events show
connection-refused readiness probes on port 8000 and liveness restarts. This is an
actual startup failure, not an overly strict revision comparison.

The public `/ready` currently returns 200 through the previous ready API revision;
that is not cutover acceptance. Diagnose the new revision before any Foundry
deployment or business acceptance. Do not rerun fresh setup after this partial
apply: verify the existing cutover schemas read-only and use the update-existing
release path for any corrected image. No schema reset, fallback acceptance or
unrelated infrastructure mutation is justified.

The fresh application and checkpoint schemas subsequently passed read-only
verification. Deployed database configuration matches the selected azd value
(compared privately, not printed). Production-construction probes reproduced
three tightly coupled defects:

| Issue | Root cause and fix | Evidence / prevention |
| --- | --- | --- |
| Missing async identity transport | The API lock omitted `aiohttp`, required by async Azure Identity. Declare it directly in API and hosted dependency inputs. | Real, unmocked model construction reproduced `ImportError` before the dependency correction. Do not rely on a hosted SDK's transitive transport dependency. |
| Keyless model constructor failure | Pinned `AzureChatOpenAI` builds both OpenAI clients; an async token provider alone leaves the sync client's constructor without credentials. Own both credential contexts and supply their corresponding providers. All actual inference stays async. | The same regression then reproduced `OpenAIError`; corrected construction passes with API-key variables absent and network access denied. A real SDK/HTTP-mock inference test proves only the async token provider is called. |
| Exporter shutdown loop and opaque failure | Root log export captured Azure SDK/exporter logs, recursively producing more export work. Startup cleanup stalled and generic log sanitization hid the original constructor failure. Scope API log export to the lane's named logger and emit a safe startup-failure event with exception class before cleanup. | A bounded full-runtime probe reached readiness but timed out inside log `force_flush` before the logger fix; it now reaches ready and closes cleanly against actual cutover storage and App Insights. No raw exception text is exported. |

Installed-wheel and isolated Python 3.13 hosted gates now also construct the real
model/credential clients without keys or network; fake-model workflow scenarios
remain separate. Hosted dependency versions did not change. These are verified
local corrections, not yet proof that a corrected cloud revision is healthy.

### Corrected rollout and hosted artifact verification

The `901634a` update-existing release subsequently passed both exact-image and
latest-ready-revision checks: API `0000014`, frontend `0000009`. Foundry direct-code
version **14** is active. Downloaded hosted archive SHA-256:
`24f7fef2ab75b9e919140ea9825e00908f4533a8f787e05be09efc6e8cff18d2`.

An artifact-verifier assumption initially rejected this valid deployment: the SDK
returns `entry_point` as `["python", "main.py"]`, not the scalar `main.py` used in
`azure.yaml`. Verification now requires that exact argv, Python 3.13 and
`remote_build`; wrong runtime, script, arguments or dependency mode still fail.
Nine targeted hosted release checks passed, and the already-downloaded v14
artifact then passed verification without rebuilding or redeploying.

Live API acceptance passed all seven scenarios, plus direct read-only PostgreSQL
checks of outcomes, refund IDs/counts, approval consumption, events and native
checkpoints. Deployed browser approval/resume and version-pinned hosted smoke
also passed. These results do not substitute for the remaining hosted matrix,
cloud judges or native trace/privacy gates.

### Latest report: cloud judges passed; hosted lifecycle and tracing remain open

Foundry v14 evaluation `eval_580d7544add645a780f4fc7d5d70604d`, run
`evalrun_0a8102b049284b8a88b4561305b27a43`, completed with **4 passed, 0 failed,
0 errored and 0 unscored**. Every item was downloaded and checked for both evaluator
decisions; results remain private under the selected agent's `.foundry/results`.

| Remaining issue | Observed evidence | Current action / completion boundary |
| --- | --- | --- |
| Full hosted matrix does not finish | Two attempts passed the first four scenarios, then failed around the next approval command. The first emitted `OperationalError`; the serial retry emitted a hosted SDK `HttpResponseError`. PostgreSQL had 33 connections against 35 ordinary slots (50 total minus 10 superuser and 5 reserved). Exact server SQLSTATE was not retained, so exhaustion is a strong hypothesis, not a proven error code. | The first failed approval had no durable decision recorded; explicit approval then resume recovered the same run successfully. Serial execution alone did not close the issue. Command-scoped hosted runtime ownership is being implemented so idle hosted compute cannot retain application pools or native saver connections. Regression/package checks and a new deployed full matrix are still required. |
| Trace ancestry gate assumes direct parents | Live v14 traces contain workflow, node, tool and model spans, plus real LangChain graph/conditional-route callback spans. Four nodes fail the current direct-parent assertion even though their ancestor chain reaches the workflow. | Preserve native framework callbacks and validate actual ancestry rather than removing legitimate framework layers or declaring the current gate passed. |
| Redundant SDK/HTTP tracing remains | Live operations still contain Azure SDK metadata/history and HTTPX model-transport spans. The original request/urllib3 opt-outs do not cover those mechanisms. | Add the supported Azure tracing opt-out and HTTPX post-constructor opt-out while retaining SDK provider ownership and native GenAI/framework tracing. These edits are not yet validated or deployed. |

One hosted smoke operation passed the prohibited-attribute-key check; that is not
full startup/privacy acceptance. The latest hosted lifecycle and telemetry edits
are **work in progress**. API/frontend remain verified revisions `0000014` and
`0000009`; the deployed hosted version remains **14**. No push/merge, schema reset,
SKU increase or MAF runtime/resource change has occurred.

The corrective candidate now closes hosted resources at each explicit command,
including errors, and performs a separate startup verification without retaining
idle database connections. The real isolated Python 3.13 hosted ASGI gate passed
start, approval, resume and an error command with a fresh runtime context and
verified close after every response. It also verifies actual Azure SDK tracing
and HTTPX/request/urllib3 opt-outs without replacing the SDK provider.
134 focused tests passed (two PostgreSQL-only cases were not selected into an
active database environment). The ancestry query now accepts the observed native
LangChain graph/route layers; actual v14 evidence passes, while broken graph
ancestry, broken model parents and empty data remain failing fixtures.
This candidate still requires a new hosted deployment and final cloud acceptance.

The hosted SDK constructor-time telemetry window is an **unverified coverage
limitation**, not a confirmed leak: the offline detector probe did not exercise its
metadata transport. Request-path cleanup and native spans passed, but live startup
and command privacy/noise checks must close that gap before final acceptance.

The approved scope includes backend organization, explicit storage setup, native
execution tracing, packaging/CI, IaC, deployment, smoke, E2E, cloud evaluations and
documentation. Work continues on `refactor/maf-backend-cutover`; no push or merge is
authorized. An independent post-implementation rubber-duck review precedes rollout.
MAF's deployment and runtime remain unchanged.

| Area | Observed issue / clarification | Action and acceptance boundary | Status |
| --- | --- | --- | --- |
| Old data | Retaining unused storage could be mistaken for a migration requirement. MAF started in a fresh schema; it did not convert legacy records or checkpoints. | LangGraph likewise starts with fresh application and native checkpoint schemas. No legacy readers, conversion, copying or preservation work; obsolete-storage deletion is separate cleanup. | Scope clarified |
| Backend ownership | Flat modules mix graph composition, persistence, command authority, runtime startup and projections. | Separate responsibilities inside the existing LangGraph package, preserving its public contracts and native graph behavior without compatibility shims. | In progress |
| Storage setup | Application SQL is a reference while startup executes embedded application and native saver DDL. | Make application migrations authoritative; keep framework migrations native and explicit. Runtime readiness must verify both selected schemas without creating or changing them. | In progress |
| Native tracing | Node/tool spans reconstructed from audit timestamps do not prove actual execution parentage. | Instrument real graph/node/model execution and verify the actual LangGraph SDK stack, async branches, usage and privacy; do not blindly copy MAF-specific fixes. | In progress |
| Delivery evidence | Existing CI already runs PostgreSQL integration, but that does not prove immutable artifacts, installed packaging, release ordering or deployed acceptance. | Preserve working coverage and add independent wheel/hosted, migration, source/digest/archive, smoke/E2E/eval and trace gates. Record actual versions/results only after execution. | In progress |
| Existing cloud baseline | The selected `langgraph` azd environment identifies active hosted version 13, but the lane's PostgreSQL server is stopped. | Verified the independent existing project/resources and model deployment read-only. Database start is deferred to approved rollout; do not mistake active hosted metadata for business readiness or change the server SKU. | Rollout pending |
| Hosted evaluation intent | The hosted YAML still pinned agent version 5 while the selected deployment is version 13; only two no-duplicate cases were present and evaluator versions were implicit. | Removed the stale target pin in favor of mandatory deployed-version verification, independently verified task-completion 19/relevance 12 in the LangGraph catalog, and extended reviewed inputs with explicit approval pause and bounded-read failure. Added fresh-group preparation and private per-item result handling; no new evaluation result claimed yet. | Implemented; acceptance pending |
| Native transport contracts | MAF and LangGraph expose different command payloads, result envelopes and health routes. | LangGraph acceptance uses `/health`, `/ready`, case-based commands and `{ok, case, events}` Responses results. It does not impose MAF's run routes or flattened results. Each hosted command owns a version-pinned session and stops it without deletion. | Implemented; acceptance pending |
| Approval-pause contract | Unlike MAF's pending outcome, LangGraph intentionally exposes `outcome: null` while paused. Copying MAF's `waiting_approval` evaluation assertion would reject correct native behavior. | Bound the hosted seed and harness to the existing LangGraph service contract: paused status, explicit checkpoint/approval state and no terminal outcome. Terminal outcome checks follow separate resume; PostgreSQL acceptance proves absence of premature side effects. | Corrected before cloud execution |
| Native saver lifecycle | `AsyncPostgresSaver.from_conn_string()` could be mistaken for another pool. | Inspected pinned checkpoint-postgres 3.1.2: it owns one async connection with autocommit, no prepared statements and dictionary rows. Keep this lifecycle separate from the audit pool and dependency-owned migrations. | Verified |
| Hosted dependency reproducibility | Hosted ranges did not identify the stack actually exercised by local gates. | Independently hash-pinned agentserver 2.1.0, Projects 2.6.0, Microsoft OTel 1.3.8, Azure Monitor 1.8.9 and OTel 1.43.0. Installed-wheel SQL and isolated Python 3.13 Responses start/approve/resume passed outside the checkout. Official PyPI worked; no mirror override required. | Local packaging verified |
| Refund receipt verification | A count of one could still refer to the wrong refund ID. | Require the verified identifier to match the durable receipt, not only its count; mismatch remains manual review rather than success. | Implemented; final matrix pending |
| Approval crash window | Consuming approval before durable result persistence could strand a reconstructed run. | Persist results before consuming approval and reconcile with native snapshots after interruption. Keep separate store ownership rather than claiming an atomic cross-store transaction. | Implemented; final matrix pending |
| Concurrent checkpoint setup | A blocking advisory-lock query retained a snapshot while native `CREATE INDEX CONCURRENTLY` waited for it, creating a deadlock. | Use bounded `pg_try_advisory_lock` polling with fully consumed autocommit queries; preserve the session lock across native setup. Release preflight likewise uses autocommit and fails immediately on contention. Interrupted diagnostic runs are not passes. | Corrected; concurrency verification pending |
| Command-lock starvation | Nine concurrent commands could occupy all eight audit-pool connections while guarded writes waited for the same pool. | Use dedicated command-lock connections rather than holding audit-pool slots during graph execution. Add real PostgreSQL concurrency/nonstarvation coverage. | Implemented; final matrix pending |

Current local evidence: 18 harness/seed contract tests passed, including actual
four-case native hosted dispatch; seven deterministic evaluations and seven API
command scenarios passed; 13 PostgreSQL migration/recovery/concurrency tests passed
on a task-owned disposable database. A further seven-scenario hosted-dispatch to
read-only SQL evidence test passed. Frontend seven tests, production build and one
browser E2E passed. Installed-wheel imports and SQL checksums passed outside checkout.
The integrated suite exposed an obsolete workspace/Bicep assertion, and the
documented hosted-package command exposed an interpreter-selection problem; these
remain explicit integration fixes, not cloud acceptance. Read-only release discovery
also needs a more specific safe diagnostic for its initial Azure CLI failure.
The independent rubber-duck review is now active; cloud mutation remains gated.

### Independent review: checkpointed validation must not depend on process memory

The reviewer reproduced a restart immediately after `detect_duplicate` using the
real shared-domain adapter, a retained native saver and a fresh service/gateway.
The checkpoint contained `duplicate_evidence`, but billing/policy validation read
only the new gateway's empty process-local cache and raised `AttributeError`.
Recovery resumes pending validation rather than rerunning duplicate detection, so
ordinary approval-breakpoint coverage did not reveal this window.

The required fix is to pass checkpointed duplicate evidence explicitly into both
validation operations and reconstruct the neutral evidence model at the adapter
boundary. A restart regression at this exact pre-validation boundary is required
before deployment.

The fix now removes the gateway evidence cache entirely. Both validation operations
require checkpointed evidence and validate it as the neutral evidence model.
PostgreSQL restart regressions cover breaks after both `detect_duplicate` and
`dispatch_validations`, with fresh gateway/model instances that reject repeated
detection or normalization. The independent reviewer confirmed that this addresses
the root cause; the parent-run integrated matrix passed **182 tests with PostgreSQL
enabled and no skips**.

All integrated Python lint and whitespace checks passed. The documented
`package_smoke.py --hosted` command now resolves an isolated Python 3.13.12
environment from hash-pinned requirements rather than accidentally using the caller's
Python 3.12 interpreter; all 121 installed dependencies were compatible and actual
offline Responses start/approval/resume plus native sampler checks passed.
The KQL completeness gate was executed against the selected LangGraph App Insights:
empty input failed, a complete synthetic parent tree passed, and a missing model
parent failed. These are query-validation results, not deployed cutover trace proof.

**Implementation/review and local acceptance are complete.** Cloud rollout,
fresh source/version/archive verification, smoke/E2E, actual cloud evaluation rows
and fresh native trace acceptance remain separate pending gates. No push or merge.

### Cloud preflight after local acceptance

The verified implementation is committed locally as `a27cb6e`. Azure ARM what-if
itself returned `ServerStoppedError` for the existing stopped LangGraph PostgreSQL
server, not a runtime failure. After review and local acceptance, that existing
server was explicitly started without a SKU/capacity change. The next full ARM
preview succeeded and was persisted privately.

The release validator then rejected ARM `Ignore` entries for resources outside the
incremental deployment, including the untouched MAF lane. This is a fail-closed
validator limitation, not authorization to change those resources. Narrow handling
of non-mutating `Ignore` entries and inspection of remaining property-level deltas
are required before apply. No application/hosted rollout or schema cutover has
occurred at this point. The task-owned disposable acceptance database was removed
after the 182-test run.

The bounded correction is now verified: the live read-only baseline preview passes.
The release template manages only the two LangGraph Container Apps and references
supporting infrastructure as existing, avoiding unrelated RBAC, connection,
PostgreSQL and service-default rewrites. All 22 unmanaged `Ignore` entries have
identical before/after payloads and no deltas. Only the two observed service-generated
app omissions are accepted; deletion, managed-app Ignore, diagnostics, supporting
resource changes and meaningful baseline deltas still fail closed. The final
immutable-image/schema preview remains mandatory before migration or rollout.

The first apply built both immutable images but correctly stopped before schema
setup or rollout when final-preview environment comparison differed. Inspection
showed Azure CLI adds empty `value` fields beside secret references and empty CORS,
while ARM omits those fields. Comparison now normalizes only empty string `value`
fields; nonempty values, secret-reference changes, ordering and other properties
remain exact. Regression coverage rejects meaningful differences. The failure did
not change application revisions or create cutover schemas.

## 2026-09-10 - Consolidated MAF refactor summary

**Functional deployment acceptance, hosted per-operation trace completeness and
SDK-noise reduction passed; destructive legacy-session cleanup is held.**
Applications remain on source `6948226`. Hosted version **8** runs `73c8693` on
`refactor/maf-backend-cutover`, preserving native 100% sampling while enforcing
SDK/HTTP instrumentation opt-outs.
This table supersedes historical interim blockers below, whose evidence is retained.
No feature-branch push or merge was performed.

| Task / area | Issue faced | Fix / completed outcome | Status |
| --- | --- | --- | --- |
| Backend organization | Flat modules mixed workflow, API, persistence, and presentation responsibilities. | Introduced explicit `api`, `application`, native `maf`, `infrastructure`, `projections`, and `testing` packages. Removed old modules without compatibility shims; LangGraph/shared runtime code stayed unchanged. | Complete |
| Migrations and restart durability | Duplicate schema setup and namespace-bound checkpoints made an implicit cutover unsafe; reconstructed in-memory wrappers lost checkpoint backing state. | Kept `backend/migrations/` authoritative, with transactional locking, version/checksum tracking, packaged SQL, startup validation, and explicit fresh-schema migration. Checkpoint views now persist per repository/run; no old checkpoint conversion or schema reset. | Complete |
| Workflow, API, and projections | Refactoring could change command semantics or allow chat to become an approval path. | Preserved 17 HTTP endpoints, 16 graph node IDs, seven scenario outcomes, durable explicit approval followed by separate resume, and read-only selected-run projections. Refunds retain idempotency plus independent verification. | Complete |
| Runtime lifecycle and packaging | API and Python 3.13 hosted execution have different dependencies and telemetry ownership. | Added explicit bootstrap/start/close boundaries, canonical entrypoints, installed-wheel SQL resources, independent hosted requirements, and host-owned telemetry lifecycle. Local API/hosted, wheel, and container gates passed. | Complete |
| Test integration and CI | Combined suites selected the wrong configuration; CI PostgreSQL settings violated the disposable-database guard. | Made MAF pytest configuration explicit and aligned CI database/user/port and fixture checks. Retained the guard against running destructive integration fixtures on remote databases. | Complete |
| Safe access logging | Removing Uvicorn's formatting arguments caused logging errors; an unconditional Uvicorn import then broke the Hypercorn-based hosted environment. | Added a safe JSON access formatter and guarded detection of already-loaded formatter classes. Verified logging with real Uvicorn and isolated hosted startup without Uvicorn installed. | Complete |
| Local/container package downloads | npm and PyPI downloads failed TLS handshakes inside containers. | Used the approved Microsoft npm/PyPI mirrors without disabling TLS or changing locked versions. Recorded the NuGet feed for future use; this lane has no NuGet build step. | Complete |
| Hosted build recovery | Forcing the same PyPI mirror into Foundry remote build caused version 4 to fail. | Removed only the hosted index override, verified the same 94 resolved package versions, and deployed hosted version 5 without resetting data or redeploying applications. | Complete |
| Browser acceptance | A browser assertion required the fake model's exact explanation wording. | Asserted successful streaming and exact rendering of the actual nonempty explanation while preserving deterministic business-outcome checks. Real-model browser E2E passed. | Complete |
| Azure preview and application rollout | PostgreSQL was stopped; ARM what-if emitted non-JSON output and coarse change classifications. | Started only the approved server with unchanged SKU; added detailed machine-readable preview and fail-closed gates. Refreshed locked images to API/frontend revisions `0000005` from `6948226`, preserving private API/public frontend and the existing schema. | Complete |
| Repeatable releases and source provenance | Fresh-cutover-only deployment could not safely update migrated data; identical hosted uploads can reuse a version. | Added explicit read-only `--update-existing` migration-history verification, with no migration/reset. Verify authoritative hosted status, exact environment, archive hash and all 73 prepared files before accepting either a new or reused version. | Complete |
| Hosted command sessions | Unstopped sessions exhausted PostgreSQL connections; CLI rejected combining invocation `--version` with `--session-id`. | Create uniquely owned sessions bound to a version, invoke by session ID only, and stop in `finally`. Stopped 28 verified task-owned sessions; all seven hosted scenarios then passed without increasing database capacity. | Complete |
| Native telemetry and correlation | The default rate-limited sampler could drop workflow/model parents while retaining children; aggregate checks missed incomplete individual traces. | Reproduced implicit-parent sampling loss, configured fixed 100% hosted sampling, and verified exact branches and native parentage for all 12 workflow executions. User confirmed full version-6 flows in both portals; version 8 preserves them. The reusable gate rejects the old broken trace and empty telemetry; privacy checks passed. | Complete |
| Hosted trace noise | SDK setup/transport spans cluttered the trace list; distro 1.3.9's second HTTP instrumentation pass ignored environment-only opt-outs. | Enforced declared HTTP opt-outs through public instrumentor APIs after SDK setup. Version 8 has zero SDK setup/HTTP spans, while all 12 workflows and 10 model calls remain complete. Added a clean command index that preserves failed and approval-only commands and leaves diagnostic logs available. | Complete |
| Evaluation seed and generated caches | Approval seed expected null instead of `waiting_approval`; nested generated results/metadata were not Git-ignored. | Corrected the seed to the existing durable-pause contract and tested every seed expectation against the hosted adapter. Added scoped cache exclusions while keeping the reviewed seed tracked and historical results intact. | Complete |
| Current deployed acceptance | Local success alone did not establish deployed durability or source provenance. | Public smoke, seven API scenarios, seven hosted scenarios, browser E2E, and read-only SQL assertions for all 14 refreshed scenario runs passed. Verified immutable image/source provenance, native telemetry, usage when supplied, and safe cross-command correlation. | Complete |
| Hosted operator authentication | Intermittent local azd credential-subprocess kills interrupted the latest harness; token prewarming failed. | Added explicit SDK transport using documented version-pinned sessions and agent-bound Responses, preserving identical assertions, fresh conversations, finally-stop and no request retries. All seven scenarios passed without global auth changes or a runtime redeploy. | Complete |
| Foundry evaluation scoring | Two four-row jobs had opaque scoring errors; restoring a historical configuration exposed one contradictory seed complaint. | Preserved failures; restored response-items/tool mappings and both judge initialization values, then clarified the requested bounded-failure behavior without weakening expectations. Pinned task-completion 19/relevance 12 produced 4 passed, 0 failed, 0 errors, 0 unscored. No model or threshold change. | Complete |
| Old-version retirement | Foundry rejects deletion while retained sessions reference a version, even when their compute is idle. | Deleted unused failed version 4 without force. Versions 1-3 retain ten idle teaching sessions; `force` would cascade-delete sessions/files, so they remain nondefault pending explicit destructive approval. Versions 5-7, current version 8 and both SQL schemas are preserved. All noise-repair sessions are idle. | Cleanup held |
| Reproducible evaluation setup | CLI defaults can silently reuse old criteria and ignore requested evaluator versions. | Added a tested setup helper that verifies catalog pins, creates a fresh group and emits a private agent-target MCP request. A new run using only this repository configuration passed all four cases and all eight evaluator decisions. | Complete |
| Final verification and handoff | Cloud gates are not a substitute for regression and source-provenance checks. | All 280 shared/backend tests, seven deterministic evaluations, Ruff, shell checks and final hosted smoke passed. Synchronized release/architecture/structure documentation; final tooling changes do not alter deployed runtime code. No push or merge. | Complete |

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
  local/review gates, the authorized rollout started that verified server and
  confirmed it Ready with the existing Burstable `Standard_B1ms` SKU. Application
  and hosted-agent cutover have not yet occurred.
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

## 2026-09-10 - Azure what-if requires the stopped MAF PostgreSQL server to start

- The reviewed, locally validated cutover source was committed on the feature branch
  as `b9ddab2`; no push or merge was performed.
- Read-only Azure preview resolved the expected MAF resources and active hosted
  version 3, but ARM returned `DeploymentWhatIfResourceError` with
  `ServerStoppedError` for the existing MAF PostgreSQL server.
- This blocks the provider's what-if operation itself, not just migration or app
  startup. Local/review gates are complete, so the approved existing-environment
  rollout must start that verified server before repeating the preview.
- No schema reset, new infrastructure, password rotation, or deployment occurred
  during the failed previews.
- The authorized server start completed successfully; state is Ready and the
  existing SKU is unchanged.

## 2026-09-10 - ARM what-if needs its explicit machine-output flag

- After PostgreSQL became Ready, the what-if command succeeded but its output was
  not valid JSON. Azure CLI's what-if formatter overrides `-o json` unless
  `--no-pretty-print` is supplied.
- The release preview now includes that documented flag. A regression covers both
  preview and apply argument lists, ensuring the preview-only flag does not leak
  into ordinary deployment commands.
- The coarse `ResourceIdOnly` result classifies resources as `Deploy`, which cannot
  support the release's create/delete and foundation-change gates. Preview now
  requests `FullResourcePayloads` internally while printing only resource IDs and
  change types. Incomplete results and undetermined change types fail closed.
- Actual detailed preview succeeded with no creates or deletes, unchanged MAF
  database/firewall/identity resources, and LangGraph resources ignored. The
  existing MAF resources marked Modify still require property-level review before
  apply; full resource payloads are not written to public logs.
- The release remained fail-closed: no migration, image upload, application rollout,
  or hosted deployment was attempted after the parse failure.
- Property-level review confirmed the existing region, Basic registry, Burstable
  PostgreSQL SKU, 32 GB storage, backup/HA settings, and network boundaries remain
  unchanged. Role differences are unresolved references to unchanged identities;
  other provider-default omissions were checked against live settings.
- A read-only connection to `model_harness_maf` succeeded using the existing
  operator access. `maf_double_charge_cutover` is absent, ready for the explicit
  fresh-schema migration. No firewall broadening was needed.
- Ruff and all 210 shared/backend tests passed, including real PostgreSQL,
  machine-output handling, incomplete/undetermined-preview rejection, and
  protection against logging full resource payloads.

## 2026-09-10 - Application cutover deployed; hosted rollout needs recovery

- Source commit `c460769ae243f2b99fc4d4121262f98859a12737` passed the detailed
  preview and was deployed from a clean feature-branch runtime snapshot.
- The reviewed foundation applied with old images/schema preserved, followed by
  the explicit baseline migration into `maf_double_charge_cutover`.
- Immutable API/frontend images use tag
  `c460769ae243f2b99fc4d4121262f98859a12737-06f843a1afb4`. Both application
  revisions `0000004` are ready. The API remains private and uses the fresh schema.
- Actual Azure public/proxied smoke, all seven API scenarios, and the browser E2E
  passed, including explicit approval/resume, uncertain-refund recovery, failed
  reads, verification mismatch, and the selected-run explanation.
- The hosted `azd deploy` step returned exit 1; the existing version `3` is still
  the azd-selected active version. Hosted recovery, new-version evaluation, and
  telemetry acceptance remain pending. Do not rerun the full fresh-schema release
  or reset already-migrated storage to retry this last deployment step.

## 2026-09-10 - Hosted remote build cannot use the local package-feed mirror

- Foundry version `4` was created but its authoritative per-version status is
  failed. A direct version-4 invocation returned `agent_version_failed` with a
  `CodeError` identifying dependency-install certificate/proxy failure.
- The user supplied mirrors conditionally for blocked package downloads. They
  solved local/container installs and the Azure ACR builds, but forcing that index
  into Foundry's separate `remote_build` environment failed.
- Hosted requirements now leave the platform's default PyPI index unchanged.
  Critical package versions are unchanged; local/API and npm mirror settings
  remain. No trusted-host exception, disabled TLS verification, firewall change,
  runtime conversion, or dependency upgrade was introduced.
- Version `4` is not an accepted release, and the existing azd-selected version `3`
  is not evidence for the new code. Recovery will deploy only hosted source after
  the corrected requirements pass local validation; existing app data is retained.
- A fresh Python 3.13 public-PyPI installation resolved the exact same 94 package
  versions as the previously validated hosted environment. Dependency compatibility,
  isolated imports, logging without Uvicorn, packaged SQL, Ruff, and all 210
  shared/backend tests passed.

## 2026-09-10 - Hosted harness sessions exhausted PostgreSQL connection slots

- Corrected hosted source deployed successfully as version `5`. The downloaded
  source archive matched all 60 expected source/SQL files and its recorded SHA-256;
  it uses the fresh schema and the same instance identity.
- Two harness attempts completed four and six scenarios respectively before a new
  session failed readiness. Exact failed-session logs showed PostgreSQL pool
  initialization timing out. A separate read-only connection attempt confirmed
  exhausted connection slots, not a password or network timeout.
- The harness was leaving every new command session running, retaining its
  PostgreSQL pool. It now creates uniquely named owned sessions explicitly and
  stops their compute in `finally`, including command/response failures. Stop
  failures remain visible with the owned session ID.
- No PostgreSQL SKU/connection-limit increase, pool-policy change, hidden command
  retry, schema reset, or application redeployment is needed for this harness fix.
  Full hosted acceptance remains pending scoped cleanup and rerun.
- All 214 shared/backend tests passed. Twenty-eight test-owned sessions were
  positively identified through request-to-native-trace correlation and durable
  test records, then stopped without deleting workflow data or old teaching
  sessions. Stopping the first verified completed session restored operator
  database access; the existing server still has its original 50-connection limit.
- Live CLI validation confirmed `invoke --session-id` must not also receive
  `--version`: the session is already bound to the explicit version at creation.
  The harness and regression now enforce that distinction. Its `finally` cleanup
  stopped the allocated session even during this argument-validation failure.
- The corrected hosted harness then passed all seven scenarios against version
  `5`, stopping each session after its command. API/browser and hosted behavior
  now pass against the same fresh schema.

## 2026-09-10 - Foundry evaluation executed, but scoring returned four errors

- Agent-target run `evalrun_c4f502016b1941f1b3636ae7aecd4221` in
  `eval_1ea80594fa1c4ec2bde07ba500bd90d1` completed against version `5`.
- All four agent responses were produced with the intended no-refund, approval
  pause, and bounded-failure behavior. Scoring reported 0 passed, 0 failed,
  4 errored, and 0 unscored; each output item had an empty evaluator-results list
  and no per-item error reason. This is not a passing evaluation.
- Full SDK output rows are retained under the selected agent's local
  `.foundry/results/maf-dev/` cache, and the run IDs/counts are recorded in its
  metadata overlay. Scoring diagnostics and telemetry/business-evidence gates
  remain in progress.

## 2026-09-10 - Cloud behavior verified; evaluation scoring still blocks acceptance

- The second agent-target run, `evalrun_c99898759e204f6a9f98b39cd5867719` in
  `eval_ed89748454c24176acc778f8f1f02911`, used verified catalog versions
  `builtin.task_completion:19` and `builtin.relevance:12`, with only the supported
  query/response mappings. It also completed with 4 total, 0 passed, 0 failed,
  4 errored, and 0 unscored. All evaluator-results lists were empty; neither the
  item nor sample contained an error reason.
- All eight actual responses across both jobs were inspected separately from
  scoring. Each matched the expected no-refund, explicit approval pause, or bounded
  read-failure contract. The second job's runs are `run-2e0a12e6a25e`,
  `run-eab1c0c7129c`, `run-0802759076fa`, and `run-8bd374f96058`.
  These response checks are not substitutes for passing evaluator scores.
- A direct probe of the existing judge deployment rejected `temperature=0` with
  HTTP 400; the same deployment successfully answered a default-temperature chat
  request. This establishes a model constraint, not the complete root cause of
  the opaque cloud scoring errors. The verified cloud catalog did not advertise
  a reasoning-model override. No undocumented flag, replacement model, threshold
  adjustment, SDK upgrade, or unbounded evaluation retry was applied.
- The seed approval expectation incorrectly used null for `terminal_status`.
  The actual hosted pause projects `waiting_approval`, with status `paused`,
  approval required, and no refund. The seed now describes that existing contract;
  the real hosted adapter is exercised with fakes against every seed expectation.
  Historical evaluation outputs/bound inputs are retained unchanged.
- Generated results and metadata were not initially excluded at the nested hosted
  agent root: the existing lane-root `.foundry` patterns did not match that path.
  Scoped ignore rules now exclude those caches while preserving the reviewed seed.
  Git-based regression checks verify both exclusions and seed visibility.
  Hosted `.agentignore` independently excludes `.foundry/` from deployment bundles.
- The selected azd environment still points to active version `5`. A fresh archive
  comparison verified all 73 files: 58 MAF package files, 13 shared package/resource
  files, plus the hosted entrypoint and requirements. The archive hash is
  `3064504d0bd63845c1122ce48fb55828e685f061528f537b12cf982695b21b52`.
  Both hosts use
  `maf_double_charge_cutover`; the old schema was neither adopted nor reset.
- Final Azure readback confirmed API/frontend revision `0000004` is each the only
  active revision receiving 100% traffic, private API/public frontend ingress is
  unchanged, and public readiness succeeds. Both image tags are locked against
  overwrite and deletion. Backend digest:
  `sha256:594877bb8e146999a58cf81f6f523e775c9a16b894d71ff2af6fa9c30efd356f`;
  frontend digest:
  `sha256:f407b8faa9fd0a57bc5f22b6730e8245e9420fd47aaab01f71c96ad25e7143bc`.
- Read-only SQL assertions verified 15 runs: seven API, seven hosted, and one
  recovered approved workflow after its old sessions stopped. Durable approvals,
  checkpoints, matching refund IDs, independent verification, retry evidence, and
  absence of false-success notifications matched the scenario contracts.
- Actual telemetry showed native parent-child workflow/executor/agent/model
  relationships and model/token fields. One retry run correlated three distinct
  start/approval/resume requests through the same safe case/run hashes, with
  distinct conversation/response hashes. Approval correlation can exist only in
  logs; queries now join request-scoped hosted identity to dependencies/logs by
  operation ID rather than requiring one role instance or request-level business ID.
  Classic success/duration fields are normalized before unions.
- The scoped safety/event scan covered 5,550 records, including eight retry and six
  workflow-failure events: no unmasked application run IDs, credential-pattern
  matches, selected raw complaints, or prohibited custom-attribute names were
  found. Some individual trace parents were absent; observed hierarchy does not
  promise complete or unsampled telemetry. The two failed API request records were
  HTTP 409 duplicate-resume rejections required by the E2E harness, not server errors.
- Final Ruff and all 217 shared/backend tests passed, including real PostgreSQL
  integration. Earlier frontend, wheel, Python 3.13 hosted, Docker, Bicep, shell,
  deterministic evaluation, real-model local, and cloud API/browser/hosted gates
  remain valid; the final changes do not alter deployed runtime code.
- Task-owned local API/UI/hosted processes, disposable PostgreSQL container and
  anonymous volume, temporary images, and three isolated virtual environments
  were removed. Both evaluation sessions were trace-correlated to these jobs and
  confirmed already stopped. Redacted evidence and ignored evaluation caches remain;
  Azure apps, version `5`, and PostgreSQL stay running.
- **Not merge-ready:** cloud scoring is unresolved. Older hosted-version definitions
  remain, with retirement deferred until acceptance; no claim is made that all old
  serving paths are retired. Work remains local on `refactor/maf-backend-cutover`;
  no feature-branch push or merge to `main` was performed.

## 2026-09-10 - Resuming end-to-end release without resetting migrated state

- The requested follow-up covers the latest MAF changes, existing-environment IaC,
  deployment, smoke, E2E, evaluations, telemetry, and documentation. The feature
  branch remains local; no push or merge is implied.
- Pending edits had reintroduced the hosted PyPI mirror override that failed in
  version 4, alongside contradictory documentation/tests. The useful API lock/CDN
  mirror assertions are retained; hosted requirements continue to use the verified
  platform-default index with TLS enabled.
- The original helper only supported a fresh-schema cutover. Added explicit
  `--update-existing` mode for later releases: it requires the currently deployed
  MAF schema and verifies complete migration history/checksums read-only before
  any cloud mutation. It never runs migrations, adopts legacy storage, or resets
  records. The original fresh-schema guard and all topology/source/readiness
  checks remain. Focused tests cover mismatch rejection, read-only verification,
  failure before foundation changes, and absence of migration on updates.
- Cloud scoring diagnostics and final new-release acceptance are in progress;
  earlier passing workflow responses are not being relabeled as passing scores.
- Local validation of this follow-up passed all 224 shared/backend tests with the
  dedicated PostgreSQL database, all seven deterministic evaluations, Ruff, four
  frontend tests, the production frontend build, Bicep compilation, and release
  shell syntax checks. Hosted source/SQL preparation completed.

## 2026-09-10 - Refreshed apps and restored cloud evaluation scoring

- The approved PostgreSQL server was stopped again at follow-up preflight. Starting
  only that server restored readiness with the same SKU. The reviewed IaC update
  preserved the existing schema, identities, firewall rules, and network boundary.
  Commit `6948226` produced API/frontend revision `0000005`; public smoke, all seven
  API scenarios, and browser E2E passed on those revisions.
- The first hosted CLI deploy failed before registering a new version. A scoped
  hosted-only retry succeeded. Foundry reused version `5` because the complete
  hosted source was identical: all 73 files and archive hash still match. Added a
  release gate that accepts either a new or reused version only after authoritative
  status, environment, archive hash, and exact prepared-file verification.
  A changed version number is not a substitute for those checks.
- A historical evaluation definition was retrieved and its actual successful
  result verified: `evalrun_bb44034286ee4a2486b4e42e04b5b90e` targeted version `2`,
  not version `3`. It supplied both judge `deployment_name` and `model` and mapped
  the response to `sample.output_items`. Reusing that configuration in a fresh
  group restored real scoring without changing the judge or thresholds.
- Diagnostic run `evalrun_442be10affd04ea7b22fb2052792ecdb` in
  `eval_dce0330d3e4540218f41ebaf449ab449` returned 3 passed, 1 failed, and 0 errors.
  Its remaining failure identified contradictory seed wording: the complaint
  required investigation "even if billing reads are unavailable", whereas the
  reviewed ground truth requires explicit bounded failure and no refund.
- Clarified only that complaint to request the existing bounded-failure behavior.
  The scenario, failed terminal status, no-refund expectation, ground truth, and
  negative-path coverage remain unchanged. No fallback refund, invented evidence,
  threshold reduction, dropped case, or runtime prompt change was used.
- Final agent-target run `evalrun_4d35eb5713e94a4c8469631a52ed26df` in
  `eval_ac18caecd4694ce4bd49e7f3380708ec` used pinned task-completion `19` and
  relevance `12` evaluators: **4 passed, 0 failed, 0 errored, 0 unscored**.
  All eight evaluator decisions and all four agent outputs were inspected.
  Task completion scored 1 on every row; relevance scored 5, 4, 4, and 5.
  The negative scenario still returns workflow status `failed` and no refund;
  its passing grade means the requested safety behavior was fulfilled.
- Restoring the historical configuration resolves the opaque-scoring blocker,
  but does not establish that temperature alone caused the original errors.
  No reasoning-model override, model deployment change, or SDK upgrade was needed.
- Hosted harness follow-up also exposed intermittent local
  `AzureDeveloperCLICredential: signal: killed` failures during token acquisition.
  Those failures remain visible and owned-session cleanup still runs. The explicit
  SDK acceptance transport below resolved the hosted verification gate, not the
  underlying CLI defect.

## 2026-09-10 - Final hosted acceptance, telemetry and safe retirement boundary

- The installed Go credential's default ten-second subprocess deadline is consistent
  with the local CLI failure, not proof of its cause. Delegated Azure CLI auth was
  already enabled; token prewarming did not fix it. Added explicit
  `hosted_harness.py --transport sdk` using documented Projects SDK sessions and
  agent-bound Responses. It never silently retries/falls back between transports.
  The selected version must be active; each command owns a version-pinned session
  and fresh conversation, and stops compute in `finally`. HTTP retries are disabled,
  clients/credentials close deterministically, and private SDK errors are not dumped.
- All seven final hosted scenarios passed on version 5:
  no duplicate `run-68a87c8fe665`, confirmed `run-5fbe5725d7fd`,
  denied `run-168e8cab7163`, retry `run-7bf92842ae76`,
  resumed approval `run-ba82ac26e070`, bounded failure `run-44a4fd047326`,
  and verification mismatch `run-f8b3aa6184b8`.
  Read-only SQL independently asserted the seven current API plus seven hosted
  runs: approvals/checkpoints, one matching ledger refund where required, actual
  verification, exact retry count, and no false-success notifications.
  Rechecking the prior 15 accepted cutover runs also passed after the update,
  demonstrating their durable records were not reset.
- Application Insights shows real native workflow/executor/agent/chat parent-child
  relationships for both runtimes. The final hosted retry run correlates three
  successful operations across three sessions, with two workflow executions, one
  retry, and model-supplied token usage. Approval correlation includes logs rather
  than requiring nonexistent workflow spans. Scoped prohibited-attribute scans
  returned no matches; selected application run IDs were hashed. Sampling still
  prevents a claim of complete traces. The two final negative-path runs emitted
  two `run.failed` events, two bounded `tool.call.failed` events on the read-failure
  run, and one independent `refund.verification` event on the mismatch run.
- Both apps remain Running at ready revision `0000005`, with the private API/public
  frontend boundary unchanged. Locked image tag:
  `6948226a3f3ac5c01741e88f708384cd4335c074-4591ddccd6c4`.
  Backend digest:
  `sha256:836750e74900e1459e2304369b7e79d9601c55362c88e8ef6ebe036d56fbb25c`;
  frontend digest:
  `sha256:ab24e11e3c20ff2664eb2fa49e6d68f93af898e6b426b2870457868ec391a745`.
  Reused hosted archive:
  `3064504d0bd63845c1122ce48fb55828e685f061528f537b12cf982695b21b52`.
- Deleted failed hosted version 4 without force. Versions 1, 2 and 3 have respectively
  five, two and three idle sessions; nonforced deletion returned HTTP 409. The SDK
  explicitly documents that `force` cascade-deletes their sessions/files. Those
  teaching artifacts were preserved rather than silently destroyed. Version 5 stays
  current/active; all 81 listed version-5 sessions were idle after acceptance. The
  old SQL schema/audit and current cutover data remain intact. Retiring all old
  definitions is therefore a separately held destructive cleanup, not a passed gate.

## 2026-09-10 - Reproducible pinned evaluation and final regression checkpoint

- Added `scripts/prepare_hosted_eval.py` and declared evaluator versions in hosted
  `eval.yaml`. The helper validates the selected deployment, all four reviewed
  contracts and catalog versions before mutation; it creates one fresh group,
  never a run, then writes a private exact `evaluation_agent_batch_eval_create`
  request. It does not clone an old cloud group or read/write `LAST_EVAL_ID`.
  Setup and response clients disable mutation retries and close deterministically.
  The CLI user-agent marker remains caller-supplied, never persisted in code/config.
- The installed beta12 CLI generates the working response-items/tool mappings and
  both judge initialization values, but ignores evaluator-version/init overrides
  and can reuse old environment criteria. Ordinary `azd eval run` and the old
  binder are therefore not the pinned acceptance path. Their documentation/output
  now direct pinned acceptance to the explicit setup helper.
- Executed the repository helper against `maf-dev`/version 5, then submitted its
  emitted request through the agent-target batch API:
  group `eval_117e25f434094efbadb14b1e5b51d0c1`,
  run `evalrun_36f2ca4232df4adc9642a91d7ee32734`.
  **4 passed, 0 failed, 0 errored, 0 unscored.** All eight evaluator decisions were
  inspected; task-completion scores were 1/1/1/1 and relevance 4/4/3/5, using
  unchanged default thresholds. Every typed seed expectation was independently
  asserted against the actual output. The approval case remains paused and the
  bounded-read case remains failed with no refund; neither was relabeled as
  completed business work. Earlier diagnostic and passing results are retained.
- Final full regression: **280 shared/backend tests passed**, including the
  dedicated loopback PostgreSQL integration suite; Ruff and shell checks passed.
  All seven deterministic evaluations also ran successfully. Frontend tests/build,
  browser E2E and Bicep checks from the deployed-source checkpoint remain valid:
  final changes affect only release/acceptance tooling, reviewed evaluation intent,
  tests and documentation, not API/frontend/shared runtime or IaC templates.
  The final typed-session SDK smoke passed as `run-f844320e26e4`.
- Authoritative readback still shows version 5 active with the exact 73-file
  archive/environment match, API/frontend Running on `0000005`, and public
  same-origin readiness returning `ready`. Application image provenance remains
  `6948226`; the final local tooling/documentation commit is not a new cloud image.
- The final evaluation's four operations were trace-correlated to one owned hosted
  session. Stopped only that session's compute, retaining filesystem and SQL state;
  all 83 current-version sessions are now idle. Removed the verified task-owned
  local PostgreSQL container and its anonymous volume after the full test run.
  Local dependency environments, retained evaluation reports and running Azure
  apps/database were left intact.

## 2026-09-10 - Screenshot review: Responses confirmed, incomplete portal trace reopened

- Confirmed the hosted entrypoint uses `ResponsesAgentServerHost` from
  `azure.ai.agentserver.responses` and registers `response_handler`; `azure.yaml`
  declares only protocol `responses`. The SDK harness uses an agent-bound OpenAI
  client and `responses.create`. Internal model calls use MAF `FoundryChatClient`,
  whose installed OpenAI base implementation calls
  `client.responses.with_raw_response.create`, not the Invocations endpoint.
  The generic telemetry name `invoke_agent` does not imply the Invocations protocol.
  An application-specific span named `foundry.responses.invoke` is not required
  for the Responses API to be in use.
- The supplied Application Insights search screenshot targets
  `mth-lg-2vq7rokaqwhae-appi`, the LangGraph component. MAF uses
  `mth-maf-wh2su65huqw5o-appi` in `rg-model-harness`; this investigation did not
  query or modify the LangGraph lane.
- Queried the exact Foundry screenshot operation
  `91fe6312caef546b7c059f420242d780`, around `14:09:51Z`. Its hashed run ID matches
  successful no-duplicate smoke `run-f844320e26e4`, not the intentional billing
  failure case. `workflow.build`, `executor.process load_account`, edges,
  normalization start/completion logs and `run.completed` are present.
  The visible HTTP 404 is not evidence that this business workflow failed;
  the request and durable outcome succeeded. Its specific HTTP target is not
  established from the deliberately redacted URL fields.
- The user's missing-parent observation is valid in the ingested data, not merely
  a collapsed tree: workflow parent `3db4c10f9628143f`, normalization executor
  parent `b26dbfaa664350d0` and model-call parent `4146816a605b0bce` are referenced
  by retained children/logs but absent as spans in that operation. Several retained
  dependencies have `itemCount = 2`, which confirms sampling according to the
  [Application Insights sampling documentation](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-sampling).
  The ARM component's `SamplingPercentage` is unset. This establishes sampled,
  incomplete telemetry, but not which SDK/export/ingestion layer dropped each span.
  Do not invent a 100-percent sampling override for the hosted platform or replace
  its provider without verifying the supported configuration.
- A separate version-5 operation, `902c13fc62e39a434db29761ffd9da8b` at
  `14:08:13Z`, contains a verified parent-ID chain:
  `workflow.run` (`1c393a0466695413`) ->
  `executor.process normalize_complaint` (`2672f8e91a1c1dd5`) ->
  `invoke_agent ComplaintNormalizer` (`27a4e38fc48a21c4`) ->
  `chat model-harness-gpt-5-6-sol` (`ed8c6a8572bd2f4a`).
  Thus native workflow/model instrumentation exists, but it is not retained
  consistently enough to claim the requested per-run portal hierarchy is complete.
- Corrected the current summary's telemetry status. The earlier aggregate native
  span/usage checks were narrower than the user's expected trace-tree acceptance.
  The remaining work is supported sampler/export/collector diagnosis and a new
  single-run parent-completeness gate, not a switch to an Invocations wrapper or
  synthetic replacement spans. Start, approval and resume remain separate durable
  commands/traces correlated by safe run IDs; no blocking HITL span is introduced.
  This confirmation changed documentation only; no runtime or cloud deployment
  settings were changed.
- The follow-up Foundry screenshot is on the correct project and agent,
  both named `model-harness-maf`, version 5. Its `902c1...` row at 09:08:13 local
  time is the verified native-chain example; `91fe63...` at 09:09:50 is the
  incomplete smoke trace. These rows are the accepted release's actual traffic.
  Subsequent screenshot investigations were read-only cloud operations, not a
  new deployment or new workflow execution. The confirmed Application Insights
  application ID is `39d900dd-2761-41a6-8841-2cf18592b62a`; hosted request spans use
  role `agentsv2`, with application spans under `model-harness-maf`.

## 2026-09-10 - Hosted trace sampling repair

- Both latest screenshots still show the old incomplete operation
  `91fe6312caef546b7c059f420242d780`; resource navigation is not the fix.
- Inspected isolated copies of the pinned agentserver 2.0.0 and
  `microsoft-opentelemetry` 1.3.9 packages. The hosted distro defaults to
  `RateLimitedSampler(5.0)`, not unconditional retention. Its exporter dependency
  is `azure-monitor-opentelemetry-exporter~=1.0.0b57`.
- Reproduced the missing-parent defect with exporter 1.0.0b57/OTel 1.44: implicit
  parent context bypasses the rate-limited sampler's explicit-parent inheritance.
  A controlled rate change retains an executor while dropping its workflow
  parent. Fixed 100% sampling retains the complete chain. Regression coverage
  includes the privacy filter in both cases and the real native MAF graph under
  fixed sampling; no fake production spans or SDK patch were introduced.
- Declared supported `microsoft.fixed_percentage` / `1.0` sampler settings in the
  hosted manifest and required them in authoritative release readback. Verified
  that the actual pinned hosted configuration resolver selects ratio `1.0`.
  The existing hosted provider/exporter, Responses protocol, content-capture
  prohibition and application runtime bundle remain unchanged. API application
  images and their sampling configuration are not part of this hosted-only fix.
- Added `observability/trace-completeness.kql`: a single-operation no-duplicate
  acceptance gate checks executed nodes, the exact four-level native parent
  chain, orphaned parents, sampling weights, and missing telemetry.
- Local telemetry/release checks passed (98 tests). Retaining all spans has an
  ingestion-cost tradeoff, appropriate here for the low-volume teaching deployment.
- Deployed hosted version **6** from configuration commit `092f284`. Readback
  verified active status, exact sampler settings, unchanged
  `maf_double_charge_cutover` schema and the original 73-file archive hash
  `3064504d0bd63845c1122ce48fb55828e685f061528f537b12cf982695b21b52`.
  No application/IaC rollout, database reset, SDK upgrade or LangGraph change.
- Repeated all seven hosted scenarios using explicit SDK transport and fresh
  version-pinned sessions: no duplicate `run-7451272727d9`, confirmed refund
  `run-1f9b2c3f4aaa`, denied approval `run-776f829012fa`, retry-safe refund
  `run-b90ca25d38b7`, resumed approval `run-aea7c8e1faa4`, bounded failure
  `run-efb8cf37e360`, and verification mismatch `run-1112ed8dcbc8`.
  All expected outcomes passed. All 17 owned sessions were subsequently verified
  idle; no retained versions, sessions, files or SQL records were deleted.
- Queried 427 safe request/dependency rows from the correct MAF Application
  Insights resource. For each of the **12 workflow executions**, asserted exact
  branch-specific executor sets, executor-to-workflow and model-to-agent-to-executor
  parent IDs, real model usage, no orphaned native parents and sampling weights of
  one. Five explicit approval commands correctly have no workflow/model spans.
- Fresh no-duplicate operation **`a6fe2589bfbd976dc4eb48e9c62d48ee`** at
  **2026-09-10 15:28:21 UTC** has all 15 native spans, four edge groups,
  three message sends and a complete normalizer/model chain (41 input / 19 output
  tokens). Its acceptance gate passes. The same query rejects the historical
  `91fe6312caef546b7c059f420242d780` operation (four orphaned native parents)
  and empty telemetry. Fixed a KQL reserved-word alias (`kind` -> `spanType`)
  exposed by live query validation before accepting the gate.
- The version-6 scoped privacy query found no prohibited attribute keys.
  The user subsequently confirmed that full flows are visible in both Foundry
  and Application Insights. Old incomplete traces cannot be repaired retroactively.
- Kept the existing reviewed `eval.yaml`/four-case dataset and pinned evaluators.
  The latest cloud judge results remain the recorded 4/4 pass on version 5;
  judges were not rerun for this configuration-only change to identical code.

## 2026-09-10 - Hosted SDK setup and transport noise

- After confirming complete flows in both portals, the user identified standalone
  `AIProjectClient.get_openai_client`, `GET /` and operational-log rows as noise.
  Do not reintroduce partial workflow sampling to remove these records.
- Inspected the pinned hosted distro and Azure Core tracing implementation.
  Standard OTel suppression does not suppress Azure Core's method decorator in
  this version; no ineffective context wrapper, private SDK patch or span-dropping
  processor was added.
- Declared supported opt-outs for Azure SDK bookkeeping and low-level HTTP
  auto-instrumentation, while retaining native MAF instrumentation and fixed 100%
  sampling. The actual hosted configuration resolver confirms these selections.
  Azure Core method tracing is explicitly disabled; warnings/errors and logs are
  not globally disabled. Low-level transport spans are intentionally unavailable
  under this policy, while native model/workflow failures remain observable.
- Added `command-traces.kql` for a request-scoped index that excludes standalone
  setup/operational entries without deleting their diagnostic records. Failed and
  approval-only commands remain visible; the workflow hierarchy is not filtered.
- Added a real Azure Projects client regression covering method-tracing opt-out
  and unchanged native parentage, plus manifest contract coverage. Local tests
  passed (101 tests), followed by Ruff. Deployed configuration commit `4afca7d`
  as hosted version **7**. Authoritative readback verified active status, exact
  instrumentation flags, unchanged schema and the same runtime archive hash.
  Existing API/frontend images, workflow source, database and LangGraph remain
  outside this change.
- Live comparison confirms `AIProjectClient.get_openai_client` spans fell from
  **17 on version 6 to zero on version 7**. HTTP spans fell from **212 to 12**
  in the current observation: ten retained POSTs belong to actual hosted command
  operations; two standalone GETs remain under investigation. These residual
  spans are not evidence that the disabled generic instrumentors were the only
  telemetry source. Do not drop command children just to achieve zero HTTP spans.
- The command-only query was executed successfully against all 17 version-6
  commands, retaining all five approval-only commands and excluding standalone
  SDK/HTTP/log operations. Version-7 final hierarchy/noise acceptance and
  documentation readback are still in progress. No push or merge was performed.
- All seven version-7 hosted scenarios subsequently passed. Further inspection
  found why residual HTTP spans survived: Microsoft distro 1.3.9 resolves the
  environment opt-outs into a separate Azure Monitor configuration object, but
  its later `_setup_instrumentations` pass reads the original options and enables
  HTTP instrumentors by default. Inspecting only the configuration resolver was
  insufficient; a real instrumentation-pass reproduction confirmed the defect.
- Added a narrow hosted startup correction: after the SDK creates its provider
  and before clients/handlers execute, honor the declared HTTP opt-outs using
  each registered instrumentor's public `uninstrument()` API. Only five explicitly
  allowed outgoing-HTTP instrumentors are eligible. Native MAF, inbound request
  instrumentation, sampling, provider/exporter ownership and logs are untouched.
  Already-disabled or absent optional instrumentors are no-ops; failed disablement
  raises explicitly instead of silently claiming the noise policy is applied.
- Verified the real pinned SDK pass enables HTTP despite the environment flag,
  then verified the startup correction disables it while native MAF remains
  enabled. Added idempotence, scope, failure and startup-order coverage.
  All 105 focused tests and Ruff passed. The required new hosted version and
  fresh live acceptance were subsequently completed as follows.
- **Final deployment:** hosted version **8**, source `73c8693`, active with exact
  environment and source verification. Archive SHA-256:
  `5875ffe17d0ce5f7446cc282861cbd19d573f5d5e07ea431dbec3d147e202f7b`.
  The only runtime changes are the hosted startup hook and its telemetry helper;
  business logic, model/prompts, Responses protocol and persistence are unchanged.
- **Noise acceptance:** the same seven-scenario comparison shows version 6
  emitting 17 SDK setup / 212 HTTP spans, version 7 emitting 0 / 12, and version 8
  emitting **0 / 0**. Native workflow/model counts remain **12 / 10** in all three.
  No residual standalone GET investigation remains open.
- **Behavior/hierarchy acceptance:** all seven version-8 scenarios passed.
  Verified exact branch-specific executor sets and every model's actual
  agent/executor/workflow parents across all 12 executions. All 236 dependency
  spans are native, with zero orphaned parents and sampling weights of one.
  The seven runs are `run-747f8f26d14b`, `run-2f8b65e7a388`,
  `run-fda93ec3ee33`, `run-393ad2ee5766`, `run-895f1256a1ee`,
  `run-f422f2462a26`, and `run-f079540eaf6b`, in harness scenario order.
- **Current trace:** no-duplicate operation
  **`5a2f13378426a7b2691f2a9ab1692dd2`**, **2026-09-10 16:07:48 UTC**,
  passes the completeness gate with 15 native spans, four edge groups, three
  message sends and no missing required spans/parents.
- **Clean view/privacy/cleanup:** the version-8 command query returns all 17
  correlated commands, including five approval-only commands, without standalone
  setup/log entries. No prohibited attribute keys were found. All 17 sessions
  for each of versions 7 and 8 are idle; no retained sessions/files/versions were
  deleted. Operational logs remain available separately. The old 24-hour view
  can still show historical noise and sampled records.
- Updated the MAF and observability READMEs with current source/version, tradeoffs,
  query links and exact evidence. The existing reviewed evaluation suite remains
  unchanged; latest cloud judge results are still explicitly the prior version-5
  4/4 result, not an unexecuted version-8 judge run. No push or merge was performed.

## 2026-09-10 - Lessons and prevention checklist

The functional release was already complete before the screenshot-driven trace
repairs and noise cleanup. Those follow-ups required three hosted rollouts
(versions 6-8). Repeating the full seven-scenario harness at every iteration added
avoidable session-startup, model-call and ingestion time. The following rules
capture both the technical lessons and a faster verification approach; they are
guidance for future work, not additional pending tasks.

| Learning | Rule for the next change |
| --- | --- |
| Successful requests and aggregate span counts hid missing parents. | Require a fresh, single-operation parent-completeness check and the branch's actual executed nodes. A chain in another run is not evidence for the selected run. Keep negative controls: the old broken trace and empty telemetry must fail the gate. |
| An unset ARM sampling percentage did not mean the SDK retained every span. | Inspect the pinned runtime's actual sampler and inherited-context behavior. Reproduce changing-rate decisions locally before changing cloud settings. Keep fixed 100% native sampling for this low-volume teaching environment; review ingestion cost separately rather than accepting broken trees. |
| A configuration resolver accepted flags that a later instrumentation pass ignored. | Exercise the complete pinned initialization path, not only parsed configuration or mocks. Supply a real SDK tracer provider in the reproduction. Verify instrumentor state after host construction and before clients/requests execute. Retest this seam when upgrading the SDK; do not assume its behavior is permanent. |
| Generic suppression did not cover Azure Core method tracing. | Verify each SDK's supported controls. Use the narrow public APIs already implemented and fail explicitly if they cannot apply the policy. Do not replace the hosted provider, patch private SDK behavior, or drop arbitrary spans to hide noise. |
| Noise reduction and trace sampling solve different problems. | Disable only the intended SDK/HTTP instrumentation and preserve native workflow, executor, agent/model, usage and message spans. Keep operational logs and failure evidence available; use a request-scoped index for a clean list. Document the loss of low-level transport diagnostics. |
| Old screenshots and 24-hour views continued to show historical problems. | Record the actual deployed version, source/archive hash, operation ID and UTC window. Compare equivalent fresh scenarios. Historical noise and sampling warnings are not proof that a new deployment regressed; a deployment cannot repair old records. |
| Span labels were mistaken for transport selection. | Verify the actual host class, manifest protocol and SDK call path. `invoke_agent` and `chat` labels do not imply the Invocations API. Do not change the working Responses protocol to address a display problem. |
| Repeating broad acceptance slowed narrow telemetry iterations. | Use focused local tests and one affected cloud scenario between candidates. Add approval/resume or failure coverage when that boundary is affected. Run the complete relevant scenario matrix after the candidate stabilizes, not automatically after every diagnostic edit. |
| Completion boundaries were not communicated clearly enough. | Report **Completed / Active / Blocked**, identify the next concrete gate, and explain why another rollout or broad rerun is needed. Distinguish a completed functional release from newly requested telemetry follow-ups. Once the requested gates pass, close the task instead of inventing more work. |

### Staged verification for future hosted telemetry changes

1. **Define the defect and acceptance criteria first.** Select the existing MAF
   environment, affected version and one representative operation. Separate
   missing hierarchy, redundant instrumentation and list-view filtering.
2. **Reproduce locally before deploying.** Use the pinned SDK initialization path,
   focused telemetry/hosted-contract tests, and privacy/provider-ownership checks.
   Confirm that the proposed control changes runtime behavior, not merely config.
3. **Use a small intermediate cloud gate.** Freeze the candidate source, deploy
   only the affected hosted service, verify its actual active version/archive and
   run the existing hosted harness with explicit `--environment <selected>`,
   `--transport sdk`, `--version <actual>` and `--smoke`.
   Check fresh ingestion with a bounded wait. Expand the scenario only when
   necessary to exercise the affected approval/resume or failure path.
4. **Run final acceptance once the candidate is stable.** Execute all seven hosted
   scenarios, assert exact native branches/parents and real model usage, compare
   noise counts, and check privacy and command correlation. A failed gate reopens
   the affected work; it must not be relabeled as a pass.
5. **Do not repeat unrelated gates without a reason.** Hosted telemetry-only work
   does not automatically require IaC, API/frontend rollouts, browser suites or
   cloud judge reruns. State which evidence was rerun and which remains a
   version-specific baseline. Changed business logic, prompts, dependencies or
   contracts require reassessing that scope.
6. **Close and persist the result.** Stop only owned sessions, retain evidence,
   update this ledger and affected READMEs, and report deliberate holds separately.
   Idle sessions are not authorization to delete their data. Push/merge remains a
   separate decision.

Reuse the existing
[parent-completeness gate](../../agent-framework/double-charge/maf/observability/trace-completeness.kql),
[command-only index](../../agent-framework/double-charge/maf/observability/command-traces.kql),
and [observability guidance](../../agent-framework/double-charge/maf/observability/README.md)
instead of rebuilding ad hoc checks on the next investigation.
