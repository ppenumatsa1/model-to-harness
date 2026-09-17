# MAF issues, changes and fixes

## Provenance and reading this ledger

This independently owned ledger was split on **2026-09-16** from the MAF sections
and MAF portions of mixed sections in the working-tree
`docs/design/issues-changes-fixes.md`. Original dates, source hashes, run/evaluation
identities, failure evidence and historical limitations are retained below.
Other-lane incidents, deployments and validation are not MAF evidence and are
excluded. Neutral lessons are stated only where they apply to MAF.

Historical observations are not fresh health checks. In particular, hosted **v8**
and API/frontend revision **0000005** predate the local outcome corrections,
three-pane workspace, command actors and business audit v2. Older "complete"
release gates remain dated results, not claims that today's source is deployed.
The initial docs/configuration implementation performed no cloud rollout, cloud
model invocation, application-database write, commit or push. Authorized integration
tests wrote only their random schemas in the dedicated disposable local database.
Subsequent parent-run local acceptance is recorded separately below.

## 2026-09-17 - MAF business-query organization refactor

Implemented on `refactor/maf-backend-cutover`, based on source `04759ba`.
The implementation-stage evidence below is historical; parent review and local
acceptance are recorded at the end of this entry. Foundry deployment, deployed
smoke/E2E/evaluations and live telemetry verification are **pending** at source
freeze. No commit, deployment, Azure database
operation, history reset, evaluation-threshold change or other-lane change was
performed by this implementation step.

Source changes:

- `backend/src/maf_double_charge/application/service.py` owns case/run workspace
  loading, case pagination, checked event queries, run-first/case-fallback
  selection, safe selected-run facts and model explanation. Commands are unchanged.
- `application/history.py` owns `CasePage`; `api/schemas.py` derives its HTTP
  response from that contract, matching the existing schema direction without
  introducing an application-to-API import.
- `projections/workspace.py` now synchronously transforms loaded state, approval,
  memory, outcome and creation time. `safe_state()` and `safe_event()` privacy
  logic is unchanged; the AG-UI import remains local to the latter.
- `api/routers/{cases,runs,streams,assistant}.py` use service methods for business
  reads. SSE framing, paging/reconnect sequence cursors, Last-Event-ID handling,
  filtering, polling, heartbeats and transport errors remain in the API.
  Assistant telemetry context remains around the service call at the HTTP
  invocation boundary; model parentage and case/run context are preserved.
- `bootstrap.py` supplies the same injected model to runner and service.
  `api/dependencies.py` removes the unused direct model dependency; the repository
  dependency remains for readiness only.
- Updated direct service constructors and stream calls in unit/integration
  tests. Evaluation and test-runtime construction already use bootstrap.
  The follow-up inspection of `infra/foundry-hosted/agent/main.py` moved its final
  event read through `service.list_events()`, preserving its response dictionary,
  full-history retry count, last-20-event tail and unchanged safe-state projection.
- Updated `architecture.md` and `projectstructure.md` for the query/projection
  boundary. No infrastructure deployment behavior was changed.

New `backend/tests/unit/test_service_queries.py` covers loaded-data purity and
non-mutation, workspace retrieval, keyset lookahead/ties, event sequence gaps,
existence checks, ambiguous case/run selection and exact model-safe facts.
Architecture tests prohibit business-router repository/model access and
projection I/O dependencies. API tests add event limits, missing-selection error
precedence and run/case explanation context/parentage, including model failure.
Existing workspace/stream tests now exercise service queries; bootstrap and
checkpoint tests verify the required model injection.

Executed from `agent-framework/double-charge/maf`:

```bash
.venv/bin/ruff check backend evals scripts
.venv/bin/python -m pytest --basetemp=.pytest-organization-refactor \
  backend/tests/unit/test_service_queries.py \
  backend/tests/unit/test_audit_stream.py \
  backend/tests/unit/test_bootstrap.py \
  backend/tests/unit/test_checkpoint_codec.py \
  backend/tests/unit/test_workflow.py \
  backend/tests/unit/test_telemetry.py \
  backend/tests/contracts/test_api.py \
  backend/tests/contracts/test_workspace.py \
  backend/tests/contracts/test_architecture.py \
  backend/tests/contracts/test_workspace_import.py \
  backend/tests/contracts/test_agui.py \
  backend/tests/contracts/test_business_audit.py \
  backend/tests/contracts/test_eval_results.py \
  backend/tests/contracts/test_release_scripts.py::test_hosted_adapter_executes_explicit_workflow_commands \
  backend/tests/contracts/test_release_scripts.py::test_hosted_handler_correlates_existing_platform_span \
  backend/tests/contracts/test_release_scripts.py::test_hosted_handler_omits_absent_platform_correlation_ids \
  backend/tests/contracts/test_release_scripts.py::test_hosted_commands_correlate_authoritative_state_before_execution
.venv/bin/python -m pytest --collect-only -q \
  backend/tests/integration/test_postgres.py \
  backend/tests/integration/test_history_maintenance.py \
  backend/tests/integration/test_postgres_event_order.py
```

Results: **Ruff passed; 201 tests passed in 27.36 seconds**. One existing
Starlette/httpx deprecation warning was emitted. The hosted adapter scenarios and
telemetry checks above are offline/injected tests, not cloud acceptance.
The changed PostgreSQL tests **collected six tests only**; none were executed
against a database in this step. An earlier validation attempt exposed a missing
parent directory for the chosen local pytest scratch path; using the lane-root
scratch path above resolved it and the complete focused run passed. Scratch
artifacts were removed afterward.

Follow-up compatibility checks:

- Compared the **complete generated OpenAPI document** to `04759ba` using two
  isolated Python interpreters and baseline package sources loaded entirely in
  memory from `git archive`. Exact structural equality passed: **18 paths and
  27 public schemas**. `/api/cases` still references
  `#/components/schemas/CasePage`, whose item reference remains `CaseSummary`.
  Canonical JSON SHA-256:
  `d2cc3396d4c7b8265c8c13aed2851ff08e0d3b6b710c1fb4b5f7fc99a6d287e7`.
- Added explicit CasePage schema assertions and a hosted business-read
  architecture guard. The hosted command test now works with a service-only
  runtime double and checks the authoritative run ID passed to `list_events()`.
- The assistant tests capture unchanged case/run correlation and direct
  request-to-model span parentage for both run-ID and case-ID selection, on
  both success and model failure; context is restored afterward.

```bash
.venv/bin/ruff check backend evals scripts infra/foundry-hosted/agent/main.py
.venv/bin/python -m pytest --basetemp=.pytest-organization-followup \
  backend/tests/contracts/test_api.py \
  backend/tests/contracts/test_architecture.py \
  backend/tests/contracts/test_workspace_import.py \
  backend/tests/contracts/test_release_scripts.py::test_hosted_adapter_executes_explicit_workflow_commands \
  backend/tests/contracts/test_release_scripts.py::test_hosted_handler_correlates_existing_platform_span \
  backend/tests/contracts/test_release_scripts.py::test_hosted_handler_omits_absent_platform_correlation_ids \
  backend/tests/contracts/test_release_scripts.py::test_hosted_commands_correlate_authoritative_state_before_execution
```

Follow-up result: **Ruff passed; 45 tests passed in 11.85 seconds**. No full suite,
database, cloud or independent-review operations were run by this implementation
step. Parent-run validation and all acceptance gates remain pending.

The subsequent parent-run local PostgreSQL suite reported **463 passed and one
failed**: the live-stream pool-release test still used a state-only service
double. The stream's new event/workspace queries therefore emitted an error
frame instead of audit/snapshot frames. Replaced that stale double in
`backend/tests/integration/test_postgres_event_order.py` with the real
`DoubleChargeService`, its PostgreSQL repository, an injected fake model and a
protocol-specced runner mock. Existing connection-release, pool-availability,
frame and idle assertions are unchanged; added assertions that neither workflow
command is invoked by observation.

Explicitly authorized targeted validation against the dedicated **loopback
Compose PostgreSQL**, with the integration fixture's disposable random schema:

```bash
.venv/bin/ruff check backend/tests/integration/test_postgres_event_order.py
.venv/bin/python scripts/with_local_db.py .venv/bin/python -m pytest \
  --basetemp=.pytest-organization-pg \
  backend/tests/integration/test_postgres_event_order.py::test_live_stream_releases_postgres_connections_before_frames_and_idle
```

**Ruff passed; one test passed in 0.92 seconds.** No application/Azure database
was used. The parent owns the full-suite rerun and independent review; this
targeted repair does not establish full or cloud acceptance.

### Parent local acceptance and independent rubber-duck review

The independent reviewer found the same stale PostgreSQL stream test double
described above and no additional significant issues. This was a test regression,
not a demonstrated production failure; the corrected test exercises the real
service/repository and preserves the connection-release assertions.

After that correction, the complete backend suite passed **464 tests, zero
failures/errors/skips**, through `scripts/with_local_db.py`; Ruff passed for
`backend evals scripts infra/foundry-hosted/agent/main.py`. Frontend acceptance
passed **57 tests** and the production build.

A separate fake-model API/UI on ports **18010/15174**, backed by real loopback
PostgreSQL and a fresh `maf_service_sep17` schema, passed API smoke, all **seven
API E2E scenarios**, the actual browser workflow (approval/reason/resume, retry
safety, audit/outcome and selected-run explanation), and **seven deterministic
evaluations**. Only these temporary preview processes were stopped afterward;
normal previews and all existing application history were retained.

Private receipts, initial failure and corrected full-suite XML are retained under
session `78c6c3f4-5e02-4c4f-93a4-068df29dc2aa`,
`files/release-20260916-workspace/maf-service-20260917/`. Its immutable
`storage-before.json` records the current Azure baseline, including every
original primary key across **80 runs**, for post-release preservation checks.
LangGraph, checkout recovery, shared code and database migrations are unchanged.

## 2026-09-16 - Repaired workspace release and complete Foundry acceptance

The guarded app-only rollout from committed source
`1b4ce1098f32ece0294d5b4b3213a7d3786c0d1e` passed in `maf-dev` on
`refactor/maf-backend-cutover`. No push was performed. Hosted **11** passed its
first SDK smoke, resolving the runtime acceptance blocker after the import fix;
the unavailable v10 remote exception is not retroactively claimed as recovered.

| Artifact | Verified identity |
| --- | --- |
| Foundry agent | `model-harness-maf`, version **11 active** |
| Hosted archive SHA-256 | `4948522a8d8640d4f4902ed0922332b34cc996db4e105cb1279dca98e245becb` |
| API revision | `mth-maf-wh2su65huqw5o-api--0000008` |
| API image digest | `da282d8954ebd706e32e81e1239d03a1efd24733473090254701b9b9a22434aa` |
| UI revision | `mth-maf-wh2su65huqw5o-web--0000008` |
| UI image digest | `cb0cb0afe069bfe006dea7e8f82361ccfb2cb4bb6f9bff7689934c4f233ed486` |

Both revisions were healthy/latest-ready, with exact source/archive/environment
readback and both tag- and manifest-scoped write/delete locks. The full-resource
preview reported **2 Modify / 22 Ignore**. Foundation and monitoring sharing were
unchanged; schema verification was read-only.

API and pinned hosted smoke passed, followed by **7/7 API E2E**, **7/7 hosted
E2E**, the deployed-browser workflow, **7/7 deterministic evaluations**, and
**14/14 native audit checks**. Explicit approval/resume, actor attribution,
framework checkpoints and verified idempotent refund receipts remained intact.

The fresh Foundry evaluation completed **4/4 passed**, with zero failed, errored
or unscored items, including the previously failing approval-pause case. Group
`eval_b5c821553456403885a387b3ca932990`, run
`evalrun_5ab9ea4b876b4f988b9346ad1afeb836`, targets version 11 with unchanged
`builtin.task_completion` **19** and `builtin.relevance` **12**. All four
per-item outputs/scores were downloaded to the ignored lane-owned Foundry cache;
metadata retains the earlier v9 result under previous evaluations.

All **16/16** fresh smoke/E2E workflow roots were present in Application Insights,
and all **8/8** hosted runs matched agent/version 11. Exact smoke operation
`300cb318e065cc55ca1b238caeac3eda` passed the hierarchy gate: one workflow root,
15 native spans, one normalizer chain, four edge groups, three messages, no
missing/orphan spans, no failed request, and maximum sampling weight one. The
Foundry project connection independently targeted the same App Insights resource
with `isSharedToAll=false`. This is programmatic verification of Foundry-linked
telemetry, not visual portal inspection.

Read-only preservation retained every original baseline key, including all
eight baseline runs. The post-acceptance snapshot contained 60 runs, 4,767 events
and 574 native checkpoints; the application migration count remained one.
The local API/UI and independent PostgreSQL stayed running; private lane `.env`
remained ignored with mode 0600. No history reset or old-case replay occurred.
New private receipts are under
`files/release-20260916-workspace/maf-hosted-repair/`. The failed v9 telemetry/eval
cohort and both failed v10 smoke receipts remain unchanged historical evidence.

## 2026-09-16 - Hosted v10 import defect and optional dependency isolation

The corrected release from `dd14df9708db552b47c6cf02985d61ca876b1a67`
deployed API/UI revisions **0000007** and hosted **v10**. Hosted source/environment
readback passed, but two fresh SDK smoke attempts failed before business
invocation. Control-plane activation was not treated as runtime acceptance.

The new hosted investigation projection imported `workspace.safe_state`, whose
module-level AG-UI constants import also loaded `ag_ui.core`. Hosted requirements
do not include `ag-ui-protocol`; the fully provisioned backend test environment
does. A fresh Python environment restored from the unchanged hosted
`requirements.txt`, without installing the backend package dependencies or
AG-UI, reproduced `ModuleNotFoundError: No module named 'ag_ui'` while importing
the actual hosted adapter from the deployed source commit. This used the real
agentserver SDK, not a stub or an artificial missing-module hook.

Moved the AG-UI constants import into `safe_event()`, its only consumer.
`safe_state()` and the hosted four-field investigation projection are unchanged;
API event allowlists and behavior remain intact. The actual corrected adapter
then imported successfully in that same isolated hosted environment, without
creating a runtime, database connection, cloud session or invocation. No
dependency declarations or versions were changed.

A permanent isolated-subprocess regression denies `ag_ui` imports and verifies
safe-state findings and the hosted subset's privacy exclusions. It failed before
the fix and passes afterward. Workspace, AG-UI and release contracts passed
**196 targeted tests**; the full backend suite, including the concurrent SDK
diagnostic tests, passed **447 tests, zero skipped**, against the dedicated
loopback PostgreSQL on port 15432. Ruff passed for the isolation source and test.
The suite retained one existing Starlette/httpx deprecation warning.

The related SDK lifecycle diagnostic improvement in `scripts/hosted_harness.py`
reports only the failing SDK phase, owned session ID, numeric HTTP status and
error class to stderr, never raw server messages. It preserves the original
exception, session cleanup and no-retry behavior. All **five** independent
`test_hosted_harness_diagnostics.py` tests are included in the **447-test**
PostgreSQL result above; the parent also verified their targeted run and Ruff.

This is a **reproduced local startup defect, not a recovered remote exception**.
Console/system logs for the stopped failed sessions returned `stream_interrupted`;
doctor skipped its hosted-active probe. The remote failure mechanism remains
unconfirmed until usable runtime evidence is available. No additional cloud
retry, commit or deployment was performed for this fix. Hosted v10 acceptance
remains blocked; the original three missing trace roots and v9 **3/4** evaluation
remain failed historical evidence.

Private session evidence is under
`files/release-20260916-workspace/maf-corrected/`: the
`maf-hosted-real-import-baseline` and `maf-hosted-real-import-fixed` receipts/logs,
`maf-agui-isolation-targeted.log`, and
`maf-agui-isolation-full-backend.log` / `.xml`.
The next fresh release/acceptance cohort will use the separate private directory
`files/release-20260916-workspace/maf-hosted-repair/`; the corrected-v10 failure
receipts remain intact.

## 2026-09-16 - First workspace rollout and acceptance findings

The approved app-only release from `275bc7e609fe0adb55775a3f257984e46e2d51a1`
deployed API/UI revisions **0000006** and hosted **v9 active**. Schema checksums,
app readiness, exact hosted source/environment and the unchanged
`ApplicationInsights.isSharedToAll=false` setting passed.

| Artifact | Verified identity |
| --- | --- |
| API image digest | `69af88f3a2339209156f7c1742140b4b2b97fb8ce99dee50d715f463f43bfbfc` |
| UI image digest | `02627bc499ec4e5c2662ffde5b5d42c0128bd74af3a3c237e4c0fa01cb07d538` |
| Hosted archive SHA-256 | `253161cb7e46d388a0705d097c660354f518c9115da0f60b074d24f8f55ecb8b` |

API and pinned hosted smoke passed; both seven-case E2E matrices, the deployed
browser workflow and seven deterministic evaluations passed. Read-only native
PostgreSQL verification passed for all 14 E2E cases, including explicit
approval/resume actors, actual terminal-status facts, native checkpoints and
verified refund receipts.

Three distinct issues were found rather than waived:

| Issue | Evidence and correction |
| --- | --- |
| Tag locks did not protect digest-scoped manifests | Independent readback found write/delete flags still true on both new manifests. Only those two manifests were locked in place; subsequent manifest/tag/digest readback passed, without rebuilding or redeploying. The release helper now locks and verifies both scopes, with regression coverage. |
| API sampling dropped workflow roots | Three of 16 fresh smoke/E2E runs lacked `workflow.run` after the ingestion deadline: `run-3faa770bca28`, `run-85b1c4dbe626`, `run-1aaa672bf6d5`. Exact-operation queries found sampled weights 2/3 and prompt ingestion, not merely missing run hashes. Azure Monitor 1.8.10 selected default `RateLimitedSampler(5.0)` because API setup omitted `sampling_ratio`. The correction is explicit 100% sampling; a new API rollout and fresh cohort are required. |
| Hosted pause response omitted investigation findings | The last 20 events were almost entirely native lifecycle events, crowding out earlier duplicate/billing/policy findings. Add a bounded `investigation` subset using the existing safe-state projection; retain the technical tail without exposing complaint, operator/reason, credentials or raw checkpoint/tool data. |

The v9 Foundry evaluation remains **3/4 passed, 1 failed**, with no errored or
unscored items: group `eval_83565352d667435bb44679dc47b6c2fd`, run
`evalrun_5c2c17bdebd0491a80c15c6432cfcbf8`. The approval-pause case safely paused
without a refund, but task-completion scoring failed because the response did not
communicate the investigation findings. The judge/rubric/threshold was not
changed to turn this result green. Per-item responses and reasons are retained.

The manifest-lock and hosted-finding corrections passed **150 release contracts**
and Ruff. Explicit `sampling_ratio=1.0` is now implemented: **43 targeted telemetry
tests** verified actual distro sampler selection without environment overrides,
including **32/32 nested workflow roots retained** with parentage/privacy intact.
The integrated backend suite passed **441 tests, zero skipped**, against isolated
local PostgreSQL. This entry does not claim the sampling fix is deployed or that the
original trace/evaluation failures disappeared. A corrected release must record
its own version, new cases and fresh acceptance separately.

## 2026-09-16 - Preserving foundation during application updates

Added a supported MAF-owned `--app-only --update-existing` release mode and
`infra/app/update-existing.bicep`. The template manages only the existing API/UI
Container Apps; it does not reapply PostgreSQL, identities, role assignments,
registry, networking or the Foundry monitoring connection. This resolves the
earlier unintended monitoring-sharing change for application-only releases.
`--update-existing` alone still uses the full-foundation path.

The new mode preserves existing app configuration and secrets, rejects unrelated
changes and drift, and retains clean-source/archive, immutable-image,
verify-only schema, full-resource Provider what-if, rollout-readiness and hosted
package verification. It rejects foundation/firewall flags rather than silently
ignoring them. Secrets remain in private secure parameters, never release output.

All **129 release contract tests**, Ruff and Bicep compilation passed. Actual
baseline and existing locked-image-digest previews each reported **2 app Modify /
22 Ignore**, with no foundation modifications or resource creation/deletion.
Early diagnostic previews failed closed while API shapes and secure parameter
structure were corrected; only the final Provider-level previews passed the
release checks. These are implementation and read-only preview results, not
deployment or post-deployment acceptance.

## 2026-09-16 - Requested Foundry release blocked at source provenance

**Subsequent authorization:** the user approved committing to the feature branch
and deploying to Foundry. The commit-approval blocker below is historical.
The release must still preserve existing foundation and monitoring-sharing
settings; deployment and acceptance results will be recorded after execution.

The user authorized deploying the completed MAF changes to the existing Foundry
project, followed by smoke, E2E, evaluations and telemetry acceptance. Local
acceptance is complete, but **this source has not been deployed**.

The release tooling requires clean, committed lane/shared source. The approved
workspace, audit, configuration and documentation changes remain uncommitted.
Permission to create a local release commit without pushing was requested; the
user was unavailable. The existing no-commit boundary and release guard were
preserved rather than bypassed or deploying the old HEAD.

The earlier read-only infrastructure preview also reported non-application
foundation changes, including database/storage, monitoring and role-assignment
properties. Unresolved ARM/default-value differences are not proof of a safe
change. These require review before any foundation apply; no database reset,
schema migration, credential rotation or role change was performed.

The final read-only review confirmed that the Application Insights connection
would change **`isSharedToAll: false -> true`**: this broadens sharing and is not
expression noise. Six RBAC principal differences matched existing live identities
and were confirmed reference-expression noise. Other writable/default property
omissions remain unresolved. There is currently no supported app-only MAF release
mode: both the initial foundation phase and final rollout use the full template.
`--update-existing` prevents SQL migration, not foundation changes. Before release,
preserve existing foundation semantics through a reviewed lane-owned release
change, or obtain explicit approval for the reconciled foundation changes.

At **21:07:47 UTC**, fresh read-only checks confirmed the existing database/schema,
public liveness/readiness, API/UI revision **0000005**, and hosted **v8 active**.
The isolated source guard rejected the current dirty source as expected.
These are existing-deployment health results, not a rollout of the new workspace.

Fresh deployed smoke, E2E, hosted evaluations and exact Foundry/Application
Insights trace checks were **not run for the new source**. Earlier versions,
evaluation results and telemetry gaps below remain historical evidence.
Read-only preservation checks still retain all eight MAF runs, 779 events,
92 native checkpoints and every baseline primary key. The normal preview remains
available on **5174 / 8010**, with its existing Azure-backed configuration.

## 2026-09-16 - Independent local PostgreSQL

Added a lane-owned PostgreSQL-only `compose.yaml`, private `.env.compose` template
and explicit `scripts/with_local_db.py` child-command wrapper. The MAF stack uses
loopback port 15432 and independently scoped network/volume; the application's
Azure-backed `.env` and existing database history were not changed.

All 353 MAF backend tests passed with PostgreSQL integration enabled against this
local stack and fake models. Independent writes, stop/restart isolation and volume
persistence were verified. The existing MAF preview was restarted after its
development reload stalled, then direct and UI-proxied readiness passed.
Root Compose/configuration were retired without deleting the old database volume;
root `shared/` remained unchanged. Foundry deployment is deferred.

## 2026-09-16 - Six demo scenarios and consolidated business rules

Merged the separate human-approval document into
[business scenarios and rules](business-rules.md). MAF now owns seven design
documents, with a six-scenario overview, plain-English walkthroughs, approval
eligibility, separate resume, refund safeguards and a compact command reference.
Lane references and the MAF links in repository navigation/article companions
were repaired; article prose and LangGraph documents were not changed.

`GET /api/scenarios` no longer advertises `verification-mismatch`, so the MAF
demo picker has six choices. The fixture, verification guard, negative
regression/evaluation coverage and existing audit history remain intact.
This is not a new manual-resolution workflow or a removal of failure handling.

Targeted API contracts, workflow tests and business-audit tests passed, as did
lint and documentation-link checks. After restarting the local MAF backend,
the real UI showed exactly the six documented choices and could still open the
existing mismatch case read-only. LangGraph's live catalogue remained at seven.
No business commands, history deletion, migration, cloud deployment, commit or
push were performed for this simplification.

## 2026-09-16 - Independent design and local configuration

Created exactly eight lane-owned design topics, with actual MAF 4+1 architecture
and workflow/boundary diagrams folded into architecture/user flow. Root design
and diagrams are source provenance only, not runtime documentation dependencies.
The lane README links every topic; existing infra/observability/cache guidance
remains operationally authoritative.

| Issue | Change and boundary |
| --- | --- |
| `.env` depended on launch cwd | Editable-source layout plus lane manifest selects only `maf/.env`. No parent/root/sibling scan; wheel/hosted packages stay environment-driven. |
| Real storage had a credential-bearing fallback | Default is empty; real runtime/storage command construction explicitly requires `DATABASE_URL`. Fully injected fakes remain usable without database/model settings. |
| Launcher bypassed canonical Settings | Root/venv-aware script invokes `maf_double_charge.main`; existing Settings host, port and development reload semantics now apply. |
| Origin default disagreed with UI | Default `FRONTEND_ORIGIN` is `http://localhost:5174`; API default stays 8010. |
| Vite port fixed; proxy process-only | `MAF_UI_PORT` and optional `MAF_API_PROXY_TARGET` use process-over-dotenv precedence. Absent proxy override derives from `HOST`/`PORT`; wildcard API binds map to loopback. |
| Browser environment exposure risk | Server config returns only validated port and credential-free HTTP(S) origin. Client dotenv loading is disabled; production build does not read lane dotenv. |
| Future private dotenv could alter tests | Autouse backend fixture disables dotenv and isolates Settings environment fields/cache; explicit fake app/evaluation factories use `_env_file=None` and disable model/export destinations. The migration CLI test also disables dotenv in its child interpreter. Browser fixtures use Vite test mode and explicit local proxies, refusing existing UI servers. |

Settings precedence is constructor values > process environment > selected dotenv
> safe defaults. Explicit `_env_file=path`/`None` overrides are preserved.
See [.env.example](../../.env.example) and
[local configuration](../../README.md#local-configuration).

Initial offline validation: **322 backend tests passed, 30 PostgreSQL tests
skipped** because the dedicated server was stopped. After the parent enabled
`127.0.0.1:5434/maf_cutover_tests`, the full backend suite passed **352 tests with
zero skips** in 49.42 seconds, including migration CLI isolation, checkpoint/restart,
event ordering and guarded history maintenance. Fixtures created/dropped only
their random MAF test schemas, not another lane's schemas or application data.
One existing Starlette/httpx deprecation warning remained. Ruff and changed shell
syntax passed. **57 frontend tests passed**, including 15 server-config/privacy
cases and a real temporary production-build secret-negative check. Production
TypeScript/Vite build, all **seven offline deterministic evaluations**, and the
**one mocked Playwright workspace test** on isolated port 5189 passed.
Vite emitted non-failing dependency directive and large-chunk warnings.
All 101 checked local documentation links/anchors resolved. The shared disposable
test server remains parent-owned; this task did not stop or reset it.
Parent-owned private dotenv preparation, process restarts and new local acceptance
were separate follow-up gates, now recorded in the dated entry below. Existing
demonstrations and stored history were preserved.

## 2026-09-16 - Business audit and command actors (local)

Original source section: "Business audit and command actors - 2026-09-16".

The right pane now shows business milestones rather than another technical log.
Recorded time, explicit actor, decision/reason and restricted evidence belong to
each event; the header is a current snapshot. Terminal event facts determine
historical resolution rather than later state being substituted retrospectively.

Start/Resume require trimmed operators; decisions require reviewer/reason.
These are supplied identities, not authentication. System work is attributed
to MAF. Version-2 actor/terminal/duplicate evidence uses existing JSON payloads,
with no migration. Resume request is distinct from continuation emitted inside
the resumed handler; refund recording, verification, uncertainty and simulated
notice remain separate. Actors and reviewer reasons are excluded from model
facts/general telemetry. API, hosted adapter, evaluation callers and the hosted
seed allowlist changed together; unreviewed extra seed fields failed closed.

Historical local verification: **338 backend tests with dedicated PostgreSQL,
no skips**, Ruff; **42 frontend tests**, production build, mocked and isolated
PostgreSQL/fake-model browser coverage, all seven API scenarios. Browser checks
restored opener/reviewer/resumer after reload, required a fresh Resume operator
and excluded technical identifiers from business evidence. These checks did not
deploy the actor contract.

### Authorized incompatible-history cleanup

The earlier explicitly authorized operation removed **159 incompatible MAF cases**
from `maf_double_charge_cutover` before `2026-09-16T16:30:33+00:00`.
Preview found no running candidate and no refund record shared with retained
cases. It removed 12,329 execution events, 84 approvals, 148 outcomes, 1,497 MAF
checkpoints, 159 selected-memory rows and 67 simulated refund-ledger rows, plus
the 159 cases/runs.

The maintenance tool previews by default. Apply requires exact schema/count and
executes one scoped locked transaction. Tests preserve compatible unfinished
version-2 cases/checkpoints and newer cases, and reject running targets, shared
refund evidence and changed counts. No schema reset or other-lane deletion
occurred. This was intentional deletion, not archival or immutable retention.

At the post-cleanup inspection there were zero incompatible pre-cutoff candidates,
zero cases and a ready schema; those counts describe that instant, not today's
history after subsequent demonstrations. The current task preserves existing
demonstrations and performs no cleanup. Old deployed writers can create
incompatible records again until upgraded. This local work does not imply a
cloud deployment, smoke, evaluation or trace acceptance.

## 2026-09-16 - Case workspace (local)

Original source section: "MAF case workspace - local implementation".

| Defect | Fix and historical evidence |
| --- | --- |
| Persisted cases not browsable | Safe `(created_at, run_id)` keyset history, ten/page and direct deep-link lookup; tests covered 25 cases, equal timestamps, inserts between pages, bad cursors and old-case lookup. |
| Start hid progress until response | Browser provides fresh case/idempotency identity and observes persisted events while synchronous Start remains pending. Delayed fake-model checks proved this through Vite and the actual nginx template. No worker or auto-retry. |
| Sequence allocation was not commit order | Short per-run transaction advisory lock before audit sequence allocation; delayed PostgreSQL commits proved later appends cannot skip an earlier event, while unrelated runs remain independent. |
| Event-only refresh missed state changes | Native SSE follows committed batches plus independently changed safe workspace snapshots; delayed/terminal/paused/disconnect/cancel/error/idle-connection paths covered. |
| Approval controls were browser-local | Read persisted decision/eligibility, support old reason-less records and require reasons for new commands. Approval alone never refunds. |
| Typed UI declarations did not sanitize JSON | Server-owned positive field selection for state, memory, event and workspace responses; forbidden-field contracts keep checkpoint/key/raw payloads internal. |

Historical backend/proxy gate: **318 backend tests**, dedicated local PostgreSQL,
no skips, Ruff, all seven API scenarios. HTTPS nginx upstream delivered audit
frames before delayed Start returned using the production template with only
`BACKEND_HOST` substituted. No infrastructure change was needed.

Historical frontend/browser gate: **21 frontend tests**, production build, mocked
and isolated PostgreSQL-backed Playwright suites. Browser acceptance loaded ten
of 25 seeded cases, reached all without duplicates, restored older deep links,
saw pending-command events and reloaded an approval before explicit resume.
The interactive Azure-connected preview was not used for mutating automation.

### Independent review regressions

The earlier read-only review reproduced and closed three lifecycle defects:

| Finding | Resolution |
| --- | --- |
| Case A explanation appeared under case B | A callback guard was insufficient with one mutable runtime client; detach/settle the old invocation before clearing/reusing it. Regression uses the installed Copilot client and overlapping SSE. |
| Refreshed history skipped cases | Bridge a new head to the loaded tail, handle initially empty history and queue refresh/load-more races. Coverage includes more than ten new cases and concurrent paging. |
| Delayed history reverted newer live status | Track per-case revisions and reject stale list overwrites; regression retains the completed snapshot over an older paused response. |

Six additional frontend regression cases were included in that final run. No
second independent review or cloud release gate was claimed. These controls do
not make application/ledger/audit writes globally atomic or add automatic crash
recovery, real payment reconciliation or production reviewer authorization.

## 2026-09-15 - Outcome corrections (local)

MAF portions of "Article-driven outcome corrections - 2026-09-15":
valid billing plus ineligible policy closes without refund; missing/invalid
evidence still fails. Exhausted uncertain refunds route to manual review with
`refund_outcome_uncertain`, not an assumed failed payment. Native routes, graph
projection, normalized outcomes and focused tests changed independently.
Retries remain per-invocation/recoverable, not a lifetime budget. These changes
were not deployed. No other lane's missing-receipt or recovery feature is
attributed to MAF here.

## 2026-09-10 - Consolidated historical MAF cutover

Original source: "2026-09-10 - Consolidated MAF refactor summary" and dated
implementation/review/release incident sections. Source remained on
`refactor/maf-backend-cutover`; no push/merge was claimed.

The cutover separated `api`, `application`, native `maf`, `infrastructure`,
`projections` and explicit `testing` packages. It preserved then-current 17 HTTP
endpoints, 16 native graph nodes and seven scenarios; these are historical counts,
not today's expanded workspace surface. SQL became version/checksum-tracked,
transactionally locked and explicitly applied; startup only verifies readiness.
Checkpoint backing became repository/run durable. There was no legacy reader,
checkpoint conversion or schema reset.

Local/API Python 3.12 and hosted Python 3.13 gained explicit lifecycle, installed
SQL resources and independent hosted requirements. Local/wheel/container/hosted,
real-model restart and native checkpoint acceptance were completed before release.

| Stage / incident | Evidence and fix |
| --- | --- |
| Implementation baseline `e1299ba` | Consolidated **200 shared/backend tests**, seven deterministic evals, four UI tests/build/container/nginx, real-model API/browser and Python 3.13 hosted matrix; wheel SQL apply/repeat/evals passed outside checkout. Azure acceptance was still pending then. |
| Dependency TLS failures | Container PyPI/npm downloads failed despite host success. Approved Microsoft mirrors fixed local/API/frontend builds without disabling TLS or changing 105 locked versions. NuGet feed was recorded but unused. |
| CI target mismatch | Align dedicated `mafdev` / `maf_cutover_tests` / loopback 5434 settings without weakening guard. CI plus PostgreSQL directory passed 27 checks. |
| Uvicorn logging regression | Clearing access arguments broke formatting; safe formatter retained allowlisted method/status only. Three real-Uvicorn tests; full suite then 192. |
| Hosted import regression | Unconditional Uvicorn import broke Hypercorn-only hosted startup; detect already-loaded formatter classes without importing Uvicorn. Isolated 3.13 logging and later 200-test gate passed. |
| Brittle browser wording | Require successful nonempty streamed explanation and exact rendering of actual output, not fake phrase `Current status is`. Real-model browser passed with deterministic outcome assertions retained. |
| Preview `b9ddab2` | Existing stopped PostgreSQL caused `DeploymentWhatIfResourceError` / `ServerStoppedError`. Only approved server was started; Burstable `Standard_B1ms` SKU unchanged. |
| What-if parsing | Require `--no-pretty-print` and `FullResourcePayloads`; coarse `Deploy`, incomplete/unknown results fail closed. Detail review preserved region/registry/database/storage/network boundaries, no creates/deletes. **210 tests** and Ruff passed. |
| Cutover rollout `c460769ae243f2b99fc4d4121262f98859a12737` | Explicit fresh `maf_double_charge_cutover` migration, app image tag `c460769ae243f2b99fc4d4121262f98859a12737-06f843a1afb4`, API/frontend `0000004`, public smoke/seven API/browser passed. Hosted deploy exit 1 was not acceptance. |
| Failed hosted v4 | `agent_version_failed`/`CodeError`: forced mirror failed in Foundry remote dependency resolution. Remove hosted-only index override, retain API/npm mirrors and TLS. Public PyPI resolved same 94 versions; 210 tests and isolated packaging passed. |
| Hosted v5 session exhaustion | Two partial harness attempts reached four and six scenarios; failed-session pool readiness and read-only connection exhaustion established slot pressure. Stop uniquely owned sessions in `finally`, no capacity change or command retry. **214 tests** passed; 28 identified sessions stopped, original 50-slot server retained. |
| CLI session invocation | Version belongs on session creation, not `invoke --session-id`; fixed arguments and finally cleanup. All seven v5 scenarios then passed. |
| Follow-up update mode | `--update-existing` verifies complete current migration history/checksums read-only and never migrates/resets/adopts. **224 tests**, seven evals, four UI tests/build, Bicep/shell and source preparation passed. |
| Refreshed app source `6948226` | API/frontend `0000005`, private API/public frontend preserved. Stopped server restarted unchanged; smoke/seven API/browser passed. Hosted-only retry reused identical v5 source; authoritative active status/environment/archive/files, not version increment, proved identity. |

### Historical immutable artifacts

| Artifact | Identity |
| --- | --- |
| Revision `0000004` backend digest | `sha256:594877bb8e146999a58cf81f6f523e775c9a16b894d71ff2af6fa9c30efd356f` |
| Revision `0000004` frontend digest | `sha256:f407b8faa9fd0a57bc5f22b6730e8245e9420fd47aaab01f71c96ad25e7143bc` |
| Revision `0000005` locked image tag | `6948226a3f3ac5c01741e88f708384cd4335c074-4591ddccd6c4` |
| Revision `0000005` backend digest | `sha256:836750e74900e1459e2304369b7e79d9601c55362c88e8ef6ebe036d56fbb25c` |
| Revision `0000005` frontend digest | `sha256:ab24e11e3c20ff2664eb2fa49e6d68f93af898e6b426b2870457868ec391a745` |
| Hosted v5/v6/v7 runtime archive | `3064504d0bd63845c1122ce48fb55828e685f061528f537b12cf982695b21b52` |
| Hosted v8 archive, source `73c8693` | `5875ffe17d0ce5f7446cc282861cbd19d573f5d5e07ea431dbec3d147e202f7b` |

V5 initially matched 60 prepared source/SQL files; later full verification matched
73 (58 MAF, 13 shared/resources, hosted main and requirements). Both hosts selected
the cutover schema; old schema records were neither converted nor reset.

### Evaluation failures, correction and reproduced pass

Original sections: "Foundry evaluation executed, but scoring returned four
errors", "Cloud behavior verified; evaluation scoring still blocks acceptance",
"Refreshed apps and restored cloud evaluation scoring", and "Reproducible pinned
evaluation and final regression checkpoint".

| Evaluation group / run | Historical result |
| --- | --- |
| `eval_1ea80594fa1c4ec2bde07ba500bd90d1` / `evalrun_c4f502016b1941f1b3636ae7aecd4221` | V5, 0 passed / 0 failed / 4 errored / 0 unscored; responses existed, evaluator lists empty, no item reason. Not a pass. |
| `eval_ed89748454c24176acc778f8f1f02911` / `evalrun_c99898759e204f6a9f98b39cd5867719` | Same four errors despite catalog pins 19/12. |
| Historical `evalrun_bb44034286ee4a2486b4e42e04b5b90e` | Verified successful definition targeted v2, not v3; both judge `model`/`deployment_name` and response-items mappings informed correction. |
| `eval_dce0330d3e4540218f41ebaf449ab449` / `evalrun_442be10affd04ea7b22fb2052792ecdb` | 3 passed / 1 failed / 0 errored; exposed contradictory complaint asking investigation despite unavailable reads. |
| `eval_ac18caecd4694ce4bd49e7f3380708ec` / `evalrun_4d35eb5713e94a4c8469631a52ed26df` | 4 passed / 0 failed / 0 errored / 0 unscored. Task completion 1/1/1/1, relevance 5/4/4/5. |
| `eval_117e25f434094efbadb14b1e5b51d0c1` / `evalrun_36f2ca4232df4adc9642a91d7ee32734` | Fresh repository-driven v5 reproduction: 4/0/0/0, all eight decisions inspected; task completion 1/1/1/1, relevance 4/4/3/5. |

All eight responses from the two errored jobs matched their business expectations;
that did not make judge errors passes. Second-job runs were `run-2e0a12e6a25e`,
`run-eab1c0c7129c`, `run-0802759076fa`, `run-8bd374f96058`.
The judge rejected `temperature=0` with HTTP 400 and accepted default temperature;
this was a model constraint, not a proven full cause of opaque scoring failures.

The approval seed was corrected from null to the actual MAF `waiting_approval`
projection. Only contradictory bounded-failure complaint wording changed;
negative behavior, ground truth, thresholds, model and SDK stayed unchanged.
Nested generated caches gained scoped ignore rules while reviewed seeds stayed
tracked. Old outputs remained historical.

`prepare_hosted_eval.py` verifies active target, reviewed contracts and catalog
pins, creates one fresh group, writes a private exact batch request and never
creates a run or mutates `LAST_EVAL_ID`. Task completion 19 and relevance 12 are
pinned. Beta12 CLI ignored requested evaluator overrides and could reuse criteria;
ordinary CLI/binder invocation was not accepted as the pinned gate. Cloud judges
were not rerun for subsequent sampling/noise-only v6-v8 releases.

### Business, SQL, telemetry and retirement evidence

The first broad v5 gate independently checked 15 durable runs (seven API, seven
hosted, one recovered after old sessions stopped), approvals/checkpoints, matching
refunds/retries/verification and no false-success notice. A scoped 5,550-record
safety scan found no tested prohibited content/keys. Two HTTP 409s were intended
duplicate-resume rejections. **217 tests** passed; absent trace parents remained
an explicit limitation, not hidden by successful business outcomes.

Intermittent local `AzureDeveloperCLICredential: signal: killed` persisted despite
delegated auth/prewarming. The Go ten-second subprocess deadline was consistent
with symptoms, not proven cause. Explicit `--transport sdk` preserved version-bound
sessions, fresh conversations, no command retries and finally-stop without
changing global auth or production runtime.

Final v5 hosted runs, in seven-scenario order:
`run-68a87c8fe665`, `run-5fbe5725d7fd`, `run-168e8cab7163`,
`run-7bf92842ae76`, `run-ba82ac26e070`, `run-44a4fd047326`,
`run-f8b3aa6184b8`. All seven plus the seven refreshed API cases passed direct
read-only SQL assertions; the prior 15 accepted records also survived update.
Approval correlation could occur in logs without a nonexistent workflow span.
Sampling still prevented complete-tree claims at this checkpoint.

Failed v4 was deleted without force. V1/v2/v3 retained five/two/three idle sessions;
nonforced deletion returned 409, and force would cascade-delete sessions/files.
That destructive retirement stayed held. V5's 81 sessions, later 83 after the
reproduced eval, were idle at inspection. Old SQL schema/audit remained.
Final tooling gate: **280 shared/backend tests**, seven deterministic evals,
Ruff/shell; final typed SDK smoke `run-f844320e26e4`. Application images were still
`6948226`, not rebuilt for tooling documentation.

## 2026-09-10 - Native trace completeness and noise repair

Original source: screenshot review, sampling repair, SDK setup/transport noise
and lessons sections. These historical repairs followed functional acceptance.

The verified host is `ResponsesAgentServerHost`/`response_handler` with manifest
`responses` and agent-bound `responses.create`; MAF's internal model client also
uses Responses. A span named `invoke_agent` does not imply the Invocations API.
One supplied screenshot showed the wrong component; the MAF component was
`mth-maf-wh2su65huqw5o-appi`, application ID
`39d900dd-2761-41a6-8841-2cf18592b62a`, hosted role `agentsv2` and application role
`model-harness-maf`. No sibling resource was changed to repair MAF.

The exact broken operation `91fe6312caef546b7c059f420242d780` around `14:09:51Z`
correlated to successful no-duplicate `run-f844320e26e4`, not billing failure.
Its HTTP 404 target was deliberately redacted and not established. Referenced
workflow `3db4c10f9628143f`, normalizer `b26dbfaa664350d0` and model parent
`4146816a605b0bce` were missing as spans; `itemCount=2` confirmed sampling,
not which layer lost each record.

V5 operation `902c13fc62e39a434db29761ffd9da8b` at `14:08:13Z` did contain
`workflow.run` `1c393a0466695413` -> normalizer `2672f8e91a1c1dd5` ->
`invoke_agent ComplaintNormalizer` `27a4e38fc48a21c4` ->
`chat model-harness-gpt-5-6-sol` `ed8c6a8572bd2f4a`. One complete trace was not
evidence that all selected operations were complete.

Pinned agentserver 2.0.0 / Microsoft distro 1.3.9 defaulted to
`RateLimitedSampler(5.0)`. Exporter 1.0.0b57 with OTel 1.44 reproduced implicit
parent context bypassing explicit-parent inheritance as rates changed. Supported
`microsoft.fixed_percentage` / `1.0` retained complete native trees without
replacing the hosted provider or synthetic production spans. The new per-operation
gate rejected missing telemetry, orphaned parents and the old broken trace.

| Release | Source and exact evidence |
| --- | --- |
| V6 | Config `092f284`; 98 local focused tests. Seven scenarios passed; 17 sessions idle. Queried 427 request/dependency rows: 12 workflows with exact branches, actual model parents/usage, weights one; five approval-only commands with no invented workflows. |
| V6 no-duplicate | `a6fe2589bfbd976dc4eb48e9c62d48ee`, `2026-09-10T15:28:21Z`: 15 native spans, four edge groups, three message sends, normalizer/model chain, 41 input/19 output tokens. Gate passed; old trace and empty input failed. Reserved KQL alias `kind` became `spanType`. |
| V7 | Config `4afca7d`; 101 local tests. Public SDK opt-outs cut setup spans from 17 to zero; HTTP fell 212 to 12 (ten command POSTs and two standalone GETs). All seven scenarios passed, but residual HTTP required investigation. |
| V8 | Source `73c8693`; 105 focused tests. Distro's second instrumentation pass ignored its resolved opt-outs; public `uninstrument()` applied after SDK setup to only five allowed outgoing-HTTP instrumentors, failing visibly if unsuccessful. Native/inbound/provider/log ownership unchanged. |
| V8 final | Seven scenarios, 12 workflows and 10 model calls passed exact parent/branch checks; 236 native dependencies, zero orphaned parents, weights one; **zero SDK setup and zero HTTP transport spans**. All 17 command sessions idle. |
| V8 no-duplicate | `5a2f13378426a7b2691f2a9ab1692dd2`, `2026-09-10T16:07:48Z`: 15 native spans, four edge groups, three message sends; completeness gate passed. |

V6 scenario runs: `run-7451272727d9`, `run-1f9b2c3f4aaa`,
`run-776f829012fa`, `run-b90ca25d38b7`, `run-aea7c8e1faa4`,
`run-efb8cf37e360`, `run-1112ed8dcbc8`.
V8 scenario runs: `run-747f8f26d14b`, `run-2f8b65e7a388`,
`run-fda93ec3ee33`, `run-393ad2ee5766`, `run-895f1256a1ee`,
`run-f422f2462a26`, `run-f079540eaf6b`.

V6/V7/V8 workflow/model counts stayed 12/10 while setup/HTTP changed 17/212,
0/12, 0/0. The user confirmed full v6 flows in both portals. V7/v8 sessions were
idle and no retained sessions/files/versions were deleted. Scoped prohibited-key
checks passed. A command-only index retained failed and approval-only commands;
operational logs remained separately available. Old sampled/noisy records cannot
be repaired retroactively, and full retention has an ingestion-cost tradeoff.

Lessons retained: test actual SDK initialization, not just configuration parsing;
prove native parent IDs per selected operation, keep negative controls, do not
hide missing ancestry with synthetic spans or arbitrary span dropping, and
distinguish native model failures from intentionally disabled HTTP diagnostics.
Use focused local reproduction and one affected scenario between candidates,
then a final relevant matrix rather than repeatedly rerunning unrelated gates.
Record version/source/archive/UTC window, stop only owned sessions and report
completed/blocked scopes honestly. These are future guidance, not new tasks.

Reuse [trace-completeness.kql](../../observability/trace-completeness.kql),
[command-traces.kql](../../observability/command-traces.kql) and
[observability guidance](../../observability/README.md).

## Initial implementation and 2026-09-01/02 MAF incidents

MAF portions of the root initial implementation/safeguards/validation and mixed
Azure/monitoring verification sections:

| Historical issue | MAF evidence, correction and limit |
| --- | --- |
| Domain and independence | Neutral validated models, deterministic simulators/fixtures/evaluation contracts; independent MAF FastAPI/React/native workflow, PostgreSQL, approval/resume and safe projections. Root PostgreSQL remained a developer dependency. |
| Side effects | Deterministic IDs/timestamps, atomic simulator idempotency, persistent fingerprint/receipt and explicit conflict rejection; AG-UI tool result/end events and real read-only selected-run runtime. |
| Initial validation limits | Shared/doc checks ran offline; Docker unavailable, PostgreSQL reconstruction tests then skipped but wired to dedicated CI; model smoke needed explicit credentials, browser checks needed local dependencies. Later gates above supersede only their corresponding limits. |
| Tool heap exhaustion, Sept 1 | Node report showed heap exhaustion around 6.1 GiB resident / 6.3 GiB peak, no JS stack or env values. Narrow discovery replaced broad recursion; local diagnostic reports ignored. Not an application defect. |
| First MAF ACR build, Sept 1 | Shared package referenced root LICENSE missing from build context; copy it before package installation. Root dockerignore excluded dependency trees/caches/private artifacts. |
| Checkpoint codec, Sept 1 | Hosted local smoke could not deserialize `RunStatus`; narrowly allowlist status/approval enums. Remote approval timestamp then required Pydantic Core `TzInfo`; focused round-trip regressions, no unrestricted codec. |
| MAF proxy 502, Sept 1 | Healthy revisions/readiness hid upstream SSL handshake reset. Nginx now sends backend FQDN as SNI via `proxy_ssl_server_name`/`proxy_ssl_name` for API and health. Revision/container logs, not unsupported AppLens/Resource Health, established diagnosis. |
| Initial hosted eval, Sept 1 | Bare `task_completion` rejected; use `builtin.*`. Completed jobs then errored because target expected `item.query`, not old `input`. Initial generic smoke used completed cases after intentional HITL pause was scored incomplete; later v5 four-case suite explicitly covers correct pause behavior. |
| MAF verification, Sept 2 | Hosted v2 active, public proxy smoke passed, MAF Insights had 141 traces without severity errors in the inspected 24-hour window. Other-lane counts/eval IDs are not reproduced as MAF results. |
| MAF deployment automation, Sept 2 | Historical script generated credentials each invocation, used latest tags, assumed `python` and wrong relative Dockerfile paths. Explicit MAF environment, persisted credentials, configurable interpreter, resolved paths and release-specific tags fixed it. No rebuild solely for script cleanup; deployed smoke/status/ledger/telemetry checked independently. Current release behavior is in infra README. |
| Monitoring connection, Sept 2 | MAF had App Insights but no Foundry project connection. Lane Bicep adds its ApplicationInsights connection and project reader access; hosted manifest stops setting platform-reserved connection string, API keeps secret injection. One matching MAF AppInsights resource verified. |
| Trace deployment, Sept 2 | MAF hosted v3 active; fresh no-duplicate, denial and retry-safe refund with separate approval/resume. MAF operation `d75d9e816211ea239f3a31f077faef34` showed hosted request, native workflow/edge/executor/model/message and same conversation key. |
| Lane guidance | `AGENTS.md` documents independence, durable approval, PostgreSQL authority, packaging, telemetry safety and required checks. No other-lane trace implementation or incident is a MAF feature. |

## Remaining boundaries

At the initial local-only documentation sync, source was uncommitted and cloud
actor-contract rollout and fresh Foundry/telemetry acceptance were deferred.
The dated release entries above supersede that deployment status, not historical
failed evidence. Parent-run local dotenv acceptance is recorded below. Old
version/session retirement remains an explicitly destructive decision, not
authorized by an idle session. No real provider reconciliation, production
reviewer identity, global transaction or automatic crash-recovery guarantee is
claimed. Existing component READMEs retain operational detail; this ledger does
not duplicate a new deployment-flow design document.

## 2026-09-16 - Parent-run local dotenv acceptance

Provenance: parent acceptance report supplied at 14:11 CDT on 2026-09-16;
this documentation sync records that evidence without repeating runtime operations.
The parent removed exactly eight superseded root design documents and two root
diagrams and verified links. At that point MAF retained eight independently owned
design topics, before the later approval-document consolidation above.

The parent created the private lane-root `.env` from the existing `maf-dev`
configuration, with mode 0600 and Git exclusion. Resolved Settings matched that
source in a private comparison launched from repository-root cwd. The backend
was restarted through `scripts/dev-backend.sh` and the UI through `npm run dev`,
without injected `.azure` values. Local API/UI ran on 8010/5174; readiness through
the UI proxy passed.

With the real `.env` present, the parent reran **352 backend tests**, **57 frontend
tests** and the production build successfully. A private scan of all **426
production output files** found none of the actual database URL, Application
Insights connection string or Foundry endpoint. This is scoped evidence for that
build and those tested values, not an unrestricted secrecy guarantee.

| Fresh case | Recorded result | Native events | Elapsed |
| --- | --- | ---: | ---: |
| `dotenv-maf-no-refund-10b222f3` | `completed_no_refund` | 37 | 31.74 s |
| `dotenv-maf-retry-10b222f3` | `completed_refunded`, verified recovery | 123 | 50.19 s |
| `dotenv-maf-review-10b222f3` | `manual_review` | 109 | 39.05 s |
| `dotenv-maf-approval-10b222f3` | Paused, no decision recorded | 69 | 24.79 s |

Browser acceptance selected each fresh case and checked its exact native-event
count, live subscription and persisted memory/outcome tabs. The retry audit showed
**Existing refund reused**, then **Refund verified**, with the reviewer recorded.
Actors used the `dotenv-demo-operator`, `dotenv-demo-reviewer` and
`dotenv-demo-resumer` identifiers; System actions remained distinct. Historical
cases remained visible after reload.

The full baseline primary-key preservation check passed: all four existing runs
were retained, with eight runs afterward. Counts changed as expected: events
391 -> 729, outcomes 3 -> 6, approvals 4 -> 6, checkpoints 46 -> 86, memory 4 -> 8,
and refund records 2 -> 4. The existing user-interacted
`demo-approval-cd3bd932` case was untouched.

At this local acceptance checkpoint, source was **local and uncommitted**. It involved no
deployment, provisioning, application-schema migration, history deletion, commit
or push. Foundry-hosted and telemetry acceptance remain deferred; the local run
does not resolve prior telemetry gaps or promote historical hosted-v8 evidence
into acceptance of the current workspace/actor changes.
