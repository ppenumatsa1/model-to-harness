# LangGraph issues, changes and fixes

This lane-owned ledger separates source/local checks from historical deployment
evidence. Historical entries were split from repository `docs/design/issues-changes-fixes.md`
as read on **2026-09-16**, specifically "LangGraph direct cutover - completed",
the LangGraph portions of "Article-driven outcome corrections", "Initial
implementation", "Important fixes and safeguards", and the dated September 1-2
LangGraph incidents. Original dates, source identities, artifact IDs, observed
limitations and superseded gate states are retained below. Other lanes' changes
and validation results are not LangGraph evidence.

Related: [requirements](prd.md), [architecture](architecture.md),
[configuration](techstack.md), [source map](projectstructure.md).

## 2026-09-16 - Release build context includes frontend server configuration

The first release attempt from source `275bc7e` stopped before building an image:
ACR run `cpp` received an external HTTP **502** while pulling `python:3.12-slim`.
A bounded retry passed the backend build (`cpq`) but failed the frontend build
(`cpr`) with `TS2307: Cannot find module './server-config'`.

The full working-tree frontend build had passed, but the release's positive
source allowlist omitted the new `frontend/server-config.ts` imported by Vite.
Added exactly that file to the existing allowlist and extended its regression
test; unrelated frontend configuration, private dotenv, caches and other lanes
remain excluded. The release contract checks and Ruff passed, and an actual
frontend build from the allowlisted staging directory passed. This verifies the
shipping context rather than using the full working tree as a substitute.

Neither failed attempt applied app revisions or deployed a hosted version.
Their failures are retained as build evidence, not reported as successful
deployments. The correction requires its own committed source and a guarded
release retry.

## 2026-09-16 - Requested Foundry release blocked at source provenance

**Subsequent authorization:** the user approved committing to the feature branch
and deploying to Foundry. The commit-approval blocker below is historical.
Deployment and acceptance results will be recorded after execution.

The user authorized deploying the completed LangGraph changes to the existing
Foundry project, followed by smoke, E2E, evaluations and telemetry acceptance.
Local acceptance below is complete, but **this source has not been deployed**.

The existing release guard requires clean, committed lane/shared source. Current
workspace, actor/audit, configuration and documentation changes are uncommitted.
Permission to create a local release commit without pushing was requested; the
user was unavailable. The prior no-commit boundary and source-provenance guard
were preserved; neither a dirty-source bypass nor an old-HEAD deployment was used.

At **21:06:57 UTC**, fresh read-only checks confirmed database readiness and both
existing schema histories, public health/readiness, API revision **0000014**,
UI revision **0000009**, and hosted **v15 active**. The isolated source guard
rejected the current dirty source as expected. Staging alone is insufficient;
a reviewed local commit is required, but the release scripts do not require a push.

Fresh deployed smoke, E2E, hosted evaluations and exact Foundry/Application
Insights trace checks were **not run for the new source**. The earlier app-only
infrastructure preview and historical active version do not establish acceptance
of these changes. Existing cloud evaluation failures and trace gaps remain open
until a new deployment is exercised and its exact run/version evidence is checked.
No migration, history deletion, cloud deployment, commit or push accompanied this
release attempt.

## 2026-09-16 - Independent case workspace and business audit alignment

Aligned the user-approved workspace behavior independently with LangGraph-native
StateGraph, interrupts, `Command(resume=...)` and PostgreSQL saver ownership.
This supersedes the earlier local entries describing polling-only selection,
optional reviewer reasons and the absence of workspace/history features.

| Issue | Change and prevention |
| --- | --- |
| Existing cases could not be reopened reliably | Add keyset-paginated history, deep-linked selection and a safe persisted workspace; preserve historical records and unknown legacy fields. |
| Approval and continuation were hard to distinguish | Require opening/resuming operator identity and a reviewer reason; record approval/denial separately from explicit checkpoint Resume. Preserve eligible historical reason-less approvals. |
| Technical events obscured business evidence | Add native committed-event SSE and business audit v2. Separate human resume requests from system continuation, explicit refund verification and immutable terminal facts. |
| Concurrent commits could be skipped by a cursor | Serialize each run's event writes before sequence allocation through commit; reconnect from the latest durable sequence. |
| Run explanations could mix selected cases | Scope the optional explainer to the selected case and safe facts; keep actors, reasons and original complaints outside added model context. |
| Scenario and approval documentation overlapped | Keep six ordinary scenario choices and one concise `business-rules.md`; retain verification-mismatch safeguards, historical cases and all seven regression/evaluation fixtures. |

**Local acceptance:** 306 backend tests passed with local PostgreSQL integration,
68 frontend unit tests, two isolated mocked browser tests, Python lint and the
frontend typecheck/build. Seven deterministic evaluations had zero mismatches;
seven real local-PostgreSQL API scenarios passed. A native legacy-checkpoint
regression resumed an eligible old reason-less approval with a newly supplied
operator, without inventing historical complaint/actor data.

Parent browser acceptance used the real API, local PostgreSQL on **25432**, native
checkpoints and a fake model, not Azure services. Four additional durable cases:

| Case | Observed result | Events |
| --- | --- | ---: |
| `95e75875-86f0-4837-8d06-737682a303bb` | No duplicate; `completed_no_refund` | 17 |
| `3f87710f-5759-47d6-80a3-23742a7511c5` | Approved, explicitly resumed, existing refund recovered and verified | 58 |
| `b210a4fa-d399-4221-9c2e-054ca88c0d25` | Denied, explicitly resumed; `closed_denied` | 42 |
| `6f25091e-2ac5-44d8-8871-789e85cdb5c0` | Approval pause left undecided; no refund | 34 |

The browser observed committed events before delivery of the Start response in
the last three cases. Approval/denial alone did not resume or submit a refund.
Explicit operator/reviewer attribution, request-before-continuation ordering,
terminal memory, paused empty memory, original complaint, 10+1 history pagination,
reload and historical selection passed. The first browser attempt used an
incorrect `run_started` text selector; the actual label is `run started`. Only the
acceptance selector was fixed; the already-created case was reconciled without
repeating Start. Its pre-response visibility is not claimed.

Read-only Azure checks retained all **104** pre-alignment LangGraph runs, **2,248**
events and **999** native checkpoints, with every baseline primary key and migration
count preserved. The normal preview remains **5173 / 8000**. Its old paused case
renders the missing original complaint as not recorded, without issuing commands.
These results do not establish cloud deployment, evaluation or trace acceptance.
The user subsequently authorized a fresh MAF/LangGraph Foundry release; its actual
outcome must be recorded separately rather than inferred from these local checks.

## 2026-09-16 - Independent local PostgreSQL

Added a lane-owned PostgreSQL-only `compose.yaml`, private `.env.compose` template
and explicit `scripts/with_local_db.py` child-command wrapper. The LangGraph stack
uses loopback port 25432 and independently scoped network/volume; the application's
Azure-backed `.env` and existing case/checkpoint history were not changed.

The pre-workspace-alignment baseline of 263 LangGraph backend tests passed with
PostgreSQL integration enabled against this local stack and fake models.
Independent writes, stop/restart isolation and volume persistence were verified.
Root Compose/configuration were retired without deleting the old database volume;
root `shared/` remained unchanged. Subsequent workspace alignment has its own
acceptance record; no Foundry rollout is implied by this local database change.

## 2026-09-16 - Lane-local configuration and independent design

**Local source change only.** No private dotenv generation, live-model/database
simulation, cloud call, deployment, schema change, history rewrite, dependency
upgrade, commit or push is part of this bounded implementation.

| Issue | Change and prevention |
| --- | --- |
| `.env` selected by launch CWD | Recognize only the lane's source-checkout layout and use its absolute root `.env`; installed/hosted packages default to process environment. Preserve constructor and `_env_file` overrides. |
| Embedded credential-bearing database default | Remove it. Real runtime/setup fail clearly for missing storage; real runtime also requires model endpoint/deployment before external setup. Full fake injection remains possible. |
| Launcher used caller paths and fixed bind | Resolve the lane and its virtualenv, call the lane `main` entrypoint, and use Settings `HOST`/`PORT`. |
| Fixed frontend port/proxy | Read only safe server keys from the lane file; process wins. Configure bind/strict port and `/api`, `/health`, `/ready` proxy. Disable automatic/public dotenv injection. |
| Dotenv telemetry silently ignored | Pass the resolved Settings to telemetry instead of reading only `os.environ`. Preserve complete-retention, capture restrictions and actual hosted opt-out checks. Never replace/close hosted SDK providers. |
| Private `.env` could affect automated checks | Fake factories explicitly disable dotenv/export. Pytest isolates application environment and blocks external Python socket connections; integration URLs must be loopback. Browser acceptance uses dedicated ports and an explicit fake-backend proxy. |
| Shared design overstated lane parity | Own exactly eight design topics, fold workflow/boundary diagrams into them, and document the current 1500 ms polling/AG-UI UI, optional reason and per-hosted-command cleanup. |

Initial integrated offline regression: **240 backend tests passed, 22 PostgreSQL
tests skipped** with `TEST_DATABASE_URL` unset; **23 frontend tests passed**.
Python lint and the TypeScript/Vite production build passed. Early targeted
failures were test fixture path/DSN assumptions and TypeScript literal/Error
constructor compatibility; these were corrected before the passing runs.
Dedicated PostgreSQL and final browser/configuration acceptance are recorded
separately after execution, never inferred from these offline results.

**Integrated local acceptance:** the final backend suite passed **263 tests with
no skips** against the parent-owned loopback PostgreSQL on port 5434, database
`maf_cutover_tests`, using only randomized LangGraph schema pairs. All **23 frontend
tests**, the TypeScript/Vite production build and **one Playwright browser case**
passed. A build with private-value sentinels in process `DATABASE_URL` and a
`VITE_*` key contained neither sentinel in its output. Python lint, shell syntax,
seven deterministic evaluation scenarios and whitespace checks passed.
All eight design files and 66 local Markdown links/anchors were checked; a
nondefault-origin CORS regression verifies allowed and rejected browser origins.
The only backend warning was the intentional duplicate ZIP member fixture; Vite
also reported existing dependency annotation/chunk-size warnings. These are local
checks, not cloud telemetry or live-model acceptance.

The private lane `.env`, local application restart and additional live simulations
are parent/operator-owned and not performed here. Existing business routes,
approval contracts, idempotency, migrations and native saver behavior are unchanged.
Current UI selection remains component-local; no paginated history, operator
capture, persistent decision workspace or business-audit-v2 feature was added.

## 2026-09-16 - Parent-reported dotenv, browser and data-preservation acceptance

This follow-on entry records parent-executed acceptance, not a new deployment.
The parent created the gitignored lane-root `.env` with mode **0600** from the
existing `.azure/langgraph` source and privately verified resolved storage,
model and telemetry settings from repository-root CWD. The actual
`scripts/dev-backend.sh` and npm launcher serve API **8000** and UI **5173**;
readiness and the UI health proxy passed.

With the real private `.env` present, **263 backend tests** passed against isolated
test storage, and **23 frontend tests** plus the production build passed.
A private scan of **426 production files** found none of the actual database URL,
Application Insights connection string or model endpoint values. Root integration
retired the eight superseded designs and two diagrams; the parent's link check
passed across 27 changed/lane documents. This lane retains exactly eight designs.

Fresh API evidence is recorded in session artifact
`files/dotenv-demos-lg-6a3de3cd.json`:

| New case | Observed result | Events | Recorded duration |
| --- | --- | ---: | ---: |
| `dotenv-lg-no-refund-6a3de3cd` | `completed_no_refund` | 10 | 8.81 s |
| `dotenv-lg-retry-6a3de3cd` | `completed_refunded`; receipt recovered and verified | 34 | 11.09 s |
| `dotenv-lg-review-6a3de3cd` | `manual_review` | 28 | 8.40 s |
| `dotenv-lg-approval-6a3de3cd` | Paused at approval, no decision | 20 | Not captured |

Selected memory persisted for the three terminal cases. An initial acceptance
assertion incorrectly required memory on the paused case; read-only reconciliation
confirmed its checkpoint, null outcome, no decision and expected
`selected_memory: {}`. No replay or data repair was required.

The unchanged browser UI also started a separate fresh `resumed-approval` case,
`case-90dd3e4a6f19`, for customer `dotenv-lg-browser`. It paused with 20 events
and visible approval/denial controls; no decision was made. This acceptance used
no React-state manipulation. The UI still has no history/open-existing-case
picker; starting this new case did not open or replay an API-created case.

Read-only preservation checks retained every baseline primary key. Runs grew
**99 -> 103 -> 104** after the four API cases and additional browser pause;
events grew **2,136 -> 2,228 -> 2,248**. Approvals grew **53 -> 55**, refund
receipts **42 -> 44**, and selected-memory rows **91 -> 94**. Application and
native-checkpoint migration row counts were unchanged. No old-case modification,
replay, migration, reset or deletion was performed.

No cloud deployment/provisioning, commit or push accompanied this acceptance.
Foundry acceptance and fresh telemetry trace/ingestion acceptance remain deferred;
resolved telemetry configuration and local success do not close prior trace gaps
or supersede the scoped historical release evidence below.

## 2026-09-15 - Article-driven outcome corrections

Provenance: LangGraph portion of the original same-titled entry.
Valid billing plus explicit policy ineligibility now closes with
`completed_no_refund`; missing/invalid evidence still fails. Exhausted uncertain
refund attempts end in `manual_review` with `refund_outcome_uncertain`, and a
response lacking a refund identifier remains uncertain. No success notification
is sent. Native routes, normalized outcomes and focused regressions were updated.
Reducers and existing parallel join semantics were preserved.

These were source-only corrections, **not deployed acceptance**. September 10
release results below describe earlier source. Retry counters are recoverable
state, not a lifetime attempt budget; live-provider reconciliation remains absent.

## 2026-09-10 - LangGraph direct cutover: final verified checkpoint

Provenance: original "LangGraph direct cutover - completed / Final verified
checkpoint - 2026-09-10". This was historical acceptance of that release, not a
claim about current service health or later uncommitted source.

| Surface | Recorded LangGraph evidence |
| --- | --- |
| Source and revisions | API/frontend source `901634a`, API `0000014`, frontend `0000009`; hosted version **15**, source `1e99986`. Work was local on `refactor/maf-backend-cutover`; no push/merge occurred. |
| Backend/storage | Independent boundaries, explicit application/native setup, verify-only startup, durable approval/resume/recovery. No legacy-data migration. |
| Local acceptance | Initial integrated PostgreSQL suite **182 passed, no skips**. Final focused lifecycle/telemetry/release check **146 passed, two PostgreSQL-only skips** in its separate run. Deterministic, frontend/browser, wheel and isolated hosted gates passed. |
| Business matrix | Seven API and seven hosted scenarios passed with direct SQL outcome/refund/approval/checkpoint evidence and deployed browser approval/resume. |
| Evaluation | Hosted v15 **4 passed, 0 failed, 0 errored, 0 unscored**; every item checked against task-completion 19 and relevance 12. |
| Native telemetry | Hosted: 17 commands, 12 workflows, 70 nodes, 10 model calls; API: 12 workflows, 70 nodes, 10 model calls. Exact branches/retries, real usage, internal ancestry, complete retention and zero HTTP transport spans verified. |
| Privacy and cleanup | Observed release window: 1,299 telemetry records, 20 worker instances, zero prohibited keys/tested signatures and zero HTTP transport spans. All 46 task-owned sessions idle, with no persisted-state/session deletion. Disposable local test resources were cleaned up. |

### Immutable historical identities

| Artifact | Recorded identity |
| --- | --- |
| API image | `mthlg2vq7rokaqwhaeacr.azurecr.io/model-harness-langgraph-backend@sha256:3c9e23c70050fbafa09c207be0ee73338408a3f145aeed3d6a71a66622b54500` |
| Frontend image | `mthlg2vq7rokaqwhaeacr.azurecr.io/model-harness-langgraph-frontend@sha256:100679e26797b38c6c7d692c75a0d71e63c6d2c87019f1bebb37ae904fa01fda` |
| Hosted v15 archive SHA-256 | `eca2d0b56c2fe62857964b2d6881fa56c1e31fd54d18a8d578be61b88bccbb96` |
| Final evaluation group/run | `eval_8cdf767bc2994123822a531d8414fa4e` / `evalrun_83c0674c78af4e1488263f7646318db0` |
| Foundry project/agent | `model-harness-langgraph` / `model-harness-langgraph` |
| Application Insights | `mth-lg-2vq7rokaqwhae-appi`; app ID `d5f711b6-7b70-4864-b76e-691925025505` |
| Representative v15 no-duplicate operation | `10ed92924d4bcb7c023d2f7ae7c54eda` |

Five approval-only operations had no invented workflow execution. A missing-case
resume produced a safe failed command with `CaseNotFoundError`. Incoming HTTP
parents may lie outside this resource; internal ancestry was checked without
inventing caller spans or dropping incoming context.

Command-scoped hosted cleanup measured **7 database client connections before,
6 after**, against 35 ordinary slots. The earlier failure's SQLSTATE was not
retained: headroom, repeated failure, retained session connections and the
successful corrected matrix are evidence, not a fabricated server error code.
Privacy acceptance is scoped to that pinned release/window, not future SDKs.
Public service access, simulator refunds and the small database remain teaching
constraints; destructive legacy cleanup was separate and was not done.

### Historical startup/readiness incident and correction

The `d6b0d09` release completed explicit fresh setup and ARM deployment, but API
revision `0000013` failed activation/deployment progress. Readiness connections
were refused on port 8000 and liveness restarted it; frontend `0000008` was ready.
The public `/ready` returned 200 through the previous ready API, which was not
acceptance of the new revision. Existing fresh schemas were subsequently verified
read-only; recovery used update-existing, not repeated fresh setup/reset.

Production-construction probes found missing async-identity transport (`aiohttp`),
an async-only token provider while `AzureChatOpenAI` constructs both sync/async
clients, and recursive root exporter logging that stalled cleanup. Fixes declared
the transport, owned both credential/client contexts while keeping inference async,
scoped API export to the lane logger and logged only the startup exception class.
Real constructor and HTTP-mocked inference checks ran without keys/network.

The `901634a` rollout passed exact-image/latest-ready checks at API `0000014` and
frontend `0000009`. Hosted v14 archive SHA-256 was
`24f7fef2ab75b9e919140ea9825e00908f4533a8f787e05be09efc6e8cff18d2`.
The artifact verifier initially assumed scalar `main.py`; the SDK reports
`["python", "main.py"]`. Exact argv, Python 3.13 and `remote_build` verification
replaced that assumption. Nine focused checks passed; the existing downloaded
archive then passed without a rebuild. Seven API scenarios, direct SQL evidence,
deployed browser and hosted smoke passed before remaining hosted gates.

### Historical v14 lifecycle and tracing gates

Evaluation `eval_580d7544add645a780f4fc7d5d70604d` /
`evalrun_0a8102b049284b8a88b4561305b27a43` scored **4/4**, no failures/errors/unscored
items. That did not close the full matrix: two attempts passed four scenarios,
then failed near an approval with `OperationalError` and later hosted
`HttpResponseError`. PostgreSQL had **33 connections / 35 ordinary slots**
(50 total less 10 superuser and 5 reserved). SQLSTATE was unavailable.
The first failed approval had not recorded a decision; explicit approval/resume
recovered that run. Serial execution alone did not fix the lifecycle.

The correction opened/closed runtime resources per hosted command and separately
at startup, including error paths. Four native node ancestry checks had also
incorrectly required direct parents despite real LangChain graph/route callbacks.
The ancestry gate now follows those layers; framework callbacks remain enabled.
Azure SDK and HTTPX redundant transports were explicitly disabled/verified.
An isolated Python 3.13 Responses gate checked start/approval/resume/error cleanup;
**134 focused tests passed**, two PostgreSQL-only cases skipped in that run.

SDK constructor-time metadata transport coverage was then an **unverified
limitation**, not a confirmed leak. The final v15 deployed startup/command window
above superseded these pending historical gates. Empty telemetry, broken graph/
model ancestry and forbidden dotted/underscored attributes still fail closed.

### Historical implementation/review and preflight

Flat modules were split into API, application, native graph, infrastructure,
projections and explicit testing packages without compatibility aliases.
Application SQL became authoritative/packaged; native saver 3.1.2 kept its
single async autocommit connection, dictionary rows and no prepared statements.
Setup/readiness, schemas and runtime lifecycles stayed independently owned.

Refund verification was tightened from count-only to matching durable receipt ID.
Result persistence was moved before approval consumption, with native-snapshot
reconciliation covering interrupted resume. A native setup advisory-lock
deadlock was fixed through bounded `pg_try_advisory_lock` polling with fully
consumed autocommit queries. Dedicated command-lock connections prevented nine
concurrent commands from starving an eight-slot audit pool.

Review reproduced restart immediately after `detect_duplicate`: native state held
evidence but a fresh gateway's process cache was empty. The cache was removed;
both validations now require explicit checkpointed neutral evidence. PostgreSQL
regressions break after `detect_duplicate` and `dispatch_validations`, with new
gateway/model instances rejecting repeated detection/normalization. The reviewer
closed the issue; the integrated **182-test/no-skip** run passed.

Historical intermediate checks included 18 harness/seed contracts, seven local
evaluations, seven API scenarios, 13 migration/recovery/concurrency checks and a
seven-scenario dispatch-to-SQL matrix. At that checkpoint the frontend had seven
tests, one browser E2E and a successful production build. Wheel imports and SQL
checksums passed outside checkout. Obsolete Bicep assertions and hosted interpreter
selection were fixed before integrated acceptance.

The isolated hosted gate selected Python 3.13.12 and verified 121 compatible
dependencies from the pinned stack: agentserver 2.1.0, Projects 2.6.0, Microsoft
OTel 1.3.8, Azure Monitor 1.8.9 and OTel 1.43.0. Native sampler/Responses checks
passed without cloud inference. The KQL completeness gate separately rejected
empty input and missing model parents and accepted a synthetic complete tree;
those were query tests, not live cutover evidence.

Preflight source `a27cb6e` encountered ARM `ServerStoppedError`; the existing
server was explicitly started without a SKU change after local acceptance.
The release validator initially rejected nonmutating unmanaged `Ignore` entries.
Its correction accepted only 22 identical before/after entries without deltas,
while rejecting managed-app Ignore, deletion and unrelated changes. The template
now manages only two Container Apps and references supporting resources.
Two observed service-generated omissions were narrowly handled.

The first immutable-image apply stopped before setup/rollout on an environment
comparison mismatch: Azure CLI included empty `value` fields beside secret refs
and empty CORS, which ARM omitted. Only empty string value fields were normalized;
meaningful values, secret changes and ordering remain exact. No schema/revision
mutation occurred in that failed preflight.

## 2026-09-01/02 - Initial deployment incidents

Provenance: original dated LangGraph entries, retained as historical implementation
lessons. Current deployment scripts may have superseded those initial mechanisms.

| Date and original incident | Historical cause, correction and evidence |
| --- | --- |
| Sep 1, deployment review rerun-safety gaps | Regenerating a database password could rotate it away from app configuration; `latest` tags hid release identity. Review required persisted-secret reuse, release-specific tags and lane-owned hosted evaluation intent before acceptance. Local adapter/backend/frontend/lint/package/Bicep checks alone were insufficient. |
| Sep 1, launcher assumed `python` | Host supplied `python3`; prerequisites failed before cloud mutation. Deployment launcher added `PYTHON_BIN` with `python3` default. |
| Sep 1, uppercase Bicep outputs | ARM normalized `AZURE` to `azurE`; empty registry/project values stopped ACR builds. Lower-camel-case outputs and matching reads fixed it. |
| Sep 1, ACR Dockerfile directory | Lane CWD plus repository-relative Dockerfile path duplicated the path. Absolute Dockerfile paths retained the repository build context for shared-package installation. |
| Sep 2, failed azd secret lookup | `|| true` let stdout `key not found` become a password. Hosted v1 was active but invalid. Exit-status-aware secret reuse/persistence and a corrected credential/new version were required before workflow acceptance. |
| Sep 2, exporter feedback loop | Root INFO logging exported exporter/SDK HTTP logs and recursively generated more export work. Logger thresholds were narrowed after instrumentation; later cutover restricted export to the named application logger. |
| Sep 2, JSON defaults interpreted as SQL placeholders | Psycopg identifier formatting treated unescaped empty JSON braces as placeholders and raised `IndexError`. Escaped literals fixed initial setup; in-memory tests had hidden the PostgreSQL-only failure. |
| Sep 2, smoke assumed `python` | Public service was reachable but the local smoke script stopped before workflow execution. It adopted `PYTHON_BIN`/`python3`. |
| Sep 2, model defaults and hosted RBAC | Explicit temperature 0.0 was unsupported by the deployed model, so omission became default. Hosted v4's new instance identity lacked model RBAC; the initial deployment path granted that instance the lane-scoped role. The specialized blueprint principal was not eligible for the role. |

After propagation, hosted **v5** passed ordinary no-duplicate and separate
start/approval/resume retry-safe scenarios. SQL verified one refund ledger row and
one distinct ID. Public React/nginx/FastAPI readiness and durable smoke passed.
Evaluation `eval_096328c4eb50463caa4cd667a36843c3` /
`evalrun_a888c01543a34d4c80b321ccf26e29a2` had **2 passed, 0 failed, 0 errored**.
The historical App Insights query found 1,723 recent traces without severity-level
errors; aggregate counts were not per-operation completeness proof.

## 2026-09-02 - Initial monitoring and trace lineage

Provenance: LangGraph portions of the original monitoring-connection, trace
hierarchy/deployment and final redaction-review entries.

The project initially had telemetry resources but no monitoring connection.
The foundation template then added the lane-specific Application Insights
connection and reader access; hosted YAML stopped setting the reserved
connection-string variable. The current existing-environment release template
references that foundation rather than recreating it.

The initial resource used `unknown_service` and lacked cohesive command ancestry.
The Responses wrapper added `foundry.responses.invoke` and the service added
`workflow.run`. A trial preview callback lacked interrupt/resume support and was
removed. At that time node/tool spans were reconstructed from durable audit
timestamps, while model dependency spans represented real calls. **The September
10 cutover replaced that historical reconstruction with actual execution spans.**

Historical v12 operation `b8a81ebbf2c277c001311545c1f160d6` connected response,
workflow, approval/refund/verification/notification, model and safe tool records.
V13 operation `8f0c52b318c7eee4761407ab00a5be25` verified the outer span's nested
`case` result correlation and terminal/current-step fields. Public durable smoke
passed after that backend revision became healthy. Fresh no-duplicate, denial and
retry-safe paths used separate decision/resume commands.

The wrapper originally read case/run fields from the result root instead of its
allowlisted `case` object. Review corrected that nesting and removed raw exception
recording/stacks because validation errors can include rejected command text.
Only exception class and safe error code remained. Uppercase `AGENTS.md` recorded
lane independence, PostgreSQL authority, explicit approval and privacy guidance.

## Initial implementation and standing limitations

The initial lane already owned native graph control, API/UI, persistence, events,
approval pause/resume, selected-run explanation, tests and evaluations. Shared
contracts supplied deterministic fixtures and simulator idempotency; a root
PostgreSQL developer service did not own migrations. Application and native
checkpoint schemas were separate, and setup used Python/Psycopg rather than a
hidden `psql` prerequisite. AG-UI used explicit result/end events and a real,
read-only selected-run runtime.

Initial validation lacked Docker, so PostgreSQL reconstruction tests were skipped
then. That historical limitation was superseded by the dated cutover database
checks, not retroactively counted as passing. Real model smoke always required
caller configuration/identity; browser E2E required the lane dependencies/browser.

Remaining boundaries: no production reviewer authentication, real payment
provider reconciliation, global atomic store transaction, automatic crash worker
or production network-security guarantee. Local checks and historical release
observations do not certify current Azure ingestion or deployment health.
