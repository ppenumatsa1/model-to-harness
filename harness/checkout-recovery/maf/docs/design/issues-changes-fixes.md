# Checkout-recovery MAF implementation ledger

## 2026-09-20 - Public demo access and polling trace cleanup

**API/UI deployed; anonymous smoke, seven API scenarios and eight browser tests
passed.** Browser Basic login is temporarily off by default. Set the frontend
`CHECKOUT_UI_AUTH_ENABLED=true` to restore it with the existing htpasswd secret.
Anyone with the UI URL can issue demo commands; reviewer labels are not verified
identities. Private API ingress/token checks, Azure identities, explicit business
approval and upstream TLS remain intact.

Successful GET/HEAD/OPTIONS API spans are suppressed at export. Command roots,
model/tool spans and failed requests remain; handled HTTP errors now carry error
status. Existing traces are not deleted. Focused backend checks passed **44 tests**;
real nginx containers verified anonymous access, opt-in login and token privacy.

| Release evidence | Result |
| --- | --- |
| API | `crmaf-q35uqmuqoh7co-api--0000003`; digest `sha256:adf678c28a62af4ad98ee22fc046c46649fdb98b29664bdb5a07050717612470` |
| UI | `crmaf-q35uqmuqoh7co-web--0000004`; digest `sha256:45fae44aea1d4be7da8100e33c16208e47c443e574fa68c27743198dd17892fd` |
| Image provenance | Immutable prior image plus two hashed source-file replacements per image; tags `access-noise-751c4fa3d6e345cb` / `access-noise-387e5eec85d523c0`, with tags and manifests locked. No dependency changes. |
| Fresh App Insights check | After 20 successful polling probes: **zero successful non-command API roots**, 25 workflow command roots, the intentional 404 probe retained, 87 model spans and 131 tool spans. Counts are spans, not logical invocations. |
| Preservation | Exact image-only configuration/identity comparison passed. No infrastructure provisioning, migrations, data deletion or new evaluations. Hosted **v5** remains active and unchanged; this patch affects API/UI behavior only. |

The laptop lost DNS while waiting for ACR build `cp6`; the queued build itself
succeeded and its original digest was reconciled without rebuilding.
For telemetry verification, Azure consumes standard HTTP method metadata and
returns `success` as text: classify API roots through command trace IDs and
normalize success, rather than assuming a missing custom method means polling.
Private source/build/deployment and acceptance receipts are retained under the
session's `files/access-noise/maf/`; the UI URL is unchanged.

## 2026-09-17 - Platform-pattern cloud release accepted

**Foundry Deploy, Smoke, E2E, Evals and Telemetry passed.** This entry supersedes
the local-only deployment deferral below. Both independent MAF lanes deployed
reviewed source `20fc44cfd7eda24dcd78996d9af562e456cdd8c1`; their distinct business
workflows and ownership boundaries remain unchanged.

Checkout environment `crmaf-20260912` now runs Hosted Agent
`checkout-recovery-maf:5`, API revision `crmaf-q35uqmuqoh7co-api--0000002`
and UI revision `crmaf-q35uqmuqoh7co-web--0000003`.
[Open the checkout UI](https://crmaf-q35uqmuqoh7co-web.icymoss-074cbdaa.northcentralus.azurecontainerapps.io).
The existing-app saved-preview/image-only path preserved application settings,
identities and infrastructure; no foundation provisioning or schema change ran.

| Gate | Fresh release evidence |
| --- | --- |
| Source and artifacts | Downloaded Hosted archive matched all **51 canonical files** and the selected environment. SHA256 `98e1d5a59c15e8e57ef93b616284fdf1e739e3340c8c020cc2e2bd9e7e7dd553`. API image SHA256 `6f5c8f00fe1594cc2d761b90afb02132047008a36a7d2f4d93dff8ecbc4ca05a`; UI image SHA256 `b20960de646f13322ad7f158eedb8b2e1c091f196ba028a728fb57a157975f74`. Source tags and manifests were locked. |
| Local source recheck | **214 checkout and 482 double-charge backend tests passed** before source freeze; earlier frontend/build/browser evidence remains recorded below. |
| Smoke and E2E | Hosted smoke and authenticated API/UI smoke passed; **7 API + 7 Hosted scenarios and 8 real-cloud Chromium tests passed**. |
| Durable business evidence | **15 selected-case deterministic PostgreSQL audits**, all **38 added cases audited**, and **7 accepted evaluation-case audits** passed. Approval, remediation idempotency and verification were checked independently of traces. |
| Native Foundry evaluation | Group `eval_188058e6d7424429b855697f94735630`, accepted run `evalrun_8ea16f99b9d947249f6f44d4bf5dcecf`: **7/7 exact-contract and scored passes**, zero errors. All output items downloaded and cached; metadata retains earlier evaluations and the failed current attempt. |
| Foundry-linked App Insights | **15 selected cases, 23 operations, 475 spans**; Hosted version **5** verified. All selected graphs rooted and acyclic, **zero internal orphans**, sampling weight **1**, zero prohibited-content/credential findings. **21 native diagnostic-parent edges** previously missing from API traces are now present. |
| Preservation | Every original primary key, both full migration records and all **11 Azure resource IDs** retained. Monitoring target unchanged, `isSharedToAll=false`. Counts changed only through acceptance activity: **116 to 154 cases**, **670 to 894 audit events**, **115 to 153 sessions**, **85 to 113 remediation records**, **15 to 21 approvals**. |

### Issues, corrections and lessons

| Issue | Resolution and learning |
| --- | --- |
| Read-only smoke harness assumed public API health | Corrected the harness to authenticate. No application authorization was weakened and no runtime source change was needed. Retained the failed smoke receipt. |
| First native evaluation encountered Azure OpenAI grader setup HTTP 500 | Retained `evalrun_06e051a3f9b54f098da6e3b64481d4ce` with zero scored outputs. Database accounting identified seven additional executed, unscored target cases; attribution to that failed run is **inferred from accounting**, not proven by scored items. Corrected the initial reconciliation, preserved/audited those cases and completed a separate successful seven-case run. Grader failure does not imply the target performed no work. |
| Local telemetry-parent coverage did not prove cloud ingestion | Exact-operation cloud queries confirmed all 21 repaired edges and unchanged sanitization. Preserve actual native IDs/parents; never synthesize parent spans or enable message capture to make a graph look complete. |
| Double-charge's additive migration was not rolling-compatible with its exact manifest guard | The separate lane needed reviewed compatibility commit `df843b5960fdf683d1ce383b34a6c07f8e3025b1`, 36 focused tests and Hosted **13** as a transition. Smoke passed before and after explicit migration 002, then final source deployed as Hosted **14**, API/UI **0000011**. Checkout required neither migration nor that bridge. |
| New Start UI could contact an old API that ignores request identity | Double-charge deployed and health-checked its new API **before** its new UI. Schema compatibility alone does not prove command compatibility. The final application retains strict migration validation; the temporary bridge was not merged into it. |
| Release failures and old evidence could be mistaken for current acceptance | Kept separate immutable attempt receipts and exact artifact/version provenance. Fleet split checkout release from parent-owned double-charge; independent rubber-duck review approved the bridge and found no high-confidence checkout closeout issues, while requiring the failed-evaluation attribution qualifier above. |

Double-charge's independent final gates also passed: smoke, **7 API + 7 Hosted
E2E**, one live browser test, API/Hosted Start replay and conflict probes, seven
deterministic evaluations, 14 native audits and **4/4 native Foundry evaluations**.
Its selected traces contain **16 workflow roots**, **8 Hosted-14 identities** and
**536 spans across 34 operations**, with 502 native spans, zero internal native
orphans, sampling weight 1 and zero prohibited attributes. See its
[release ledger](../../../../../agent-framework/double-charge/maf/docs/design/issues-changes-fixes.md)
for the exact evaluation, migration and preservation evidence.

Session evidence is retained under `release-20260917-patterns/checkout/` (including
`checkout-release-summary.json`, corrected failed-evaluation reconciliation,
source proofs, output items, trace graphs and preservation receipts).
Double-charge command evidence is under
`release-20260916-workspace/maf-pattern-final-20260917/`; deployment/preservation
receipts are under `release-20260917-patterns/double-charge/`.
Final independent evidence/ledger review approved closeout with no
high-confidence blockers or overclaims.
No LangGraph/shared-runtime changes, dependency upgrades, role changes,
credential rotation, data deletion or push accompanied this release.

## 2026-09-17 - Local platform-pattern alignment

**At local source freeze, cloud deployment was deferred; the accepted release is
recorded above.** The two MAF
examples now use consistent responsibility boundaries without sharing runtime
code or pretending their business workflows are identical. Checkout keeps its
synchronous application state machine and bounded read-only harness;
double-charge keeps async native workflow/checkpoint continuation. No LangGraph
or framework-neutral shared source was changed.

| Issue | Change and learning |
| --- | --- |
| The API exporter dropped native intermediate parents | Retain every received span's real IDs and parent, while replacing dynamic names with fixed safe categories and stripping content, events, links, trace state, unsafe scope/resource values and error descriptions. Native MAF tool-parent tests cover child-first export across batches of 1, 2 and 100. Never fabricate parent links or confuse local graph preservation with cloud ingestion. Hosted remains SDK-provider-owned. |
| Configuration/launch behavior differed by lane | Add editable lane-only dotenv discovery, explicit > process > dotenv > default precedence, environment-only installed/Hosted behavior and `_env_file=None` isolation. Add configurable loopback launchers and server-only Vite settings without publishing secrets. Preserve the scripted development default and existing keys. |
| Business code imported concrete telemetry | Add a checkout-owned injected instrumentation port. Runtime owns concrete wiring and health; business routers use the service, and health routes use the runtime-health dependency. API and Hosted dispatch application-owned command/error contracts while preserving existing public service methods. |
| New dotenv discovery could contaminate older tests | Parent validation added suite-wide dotenv disabling to the existing process-isolation fixture. Explicit dotenv tests use their own synthetic files. Do not rely on a developer's current absence of private configuration. |
| Double-charge refund idempotency did not deduplicate Start | Independently add optional Start UUID claims/receipts and same-intent browser retries. Its additive migration is double-charge-only; checkout keeps its existing transactional request identity and needs no schema change. Pending double-charge claims require inspection, not automatic replay. |
| Review found a post-claim failure could look like definite validation rejection | A real double-charge model `ValueError` reproduced HTTP 422 after a run existed. Add a safe execution-error boundary after claim; API 500 and Hosted typed failures preserve the browser's original retry identity. The reviewer confirmed the fix. |
| Operational/design guidance described older source | Update seven-file design navigation, actual command/instrumentation/configuration responsibilities and lane-owned release guidance. Keep failed cloud attempts and earlier telemetry limitations as dated history rather than rewriting them as current acceptance. |

### Local evidence

| Gate | Result |
| --- | --- |
| Checkout backend, real loopback PostgreSQL and Hosted contracts | **214 passed, zero skips** using `scripts/with_local_db.py -- .venv/bin/python -m pytest backend/tests`. Includes transactional/restart, business/evaluation, harness, packaging and telemetry coverage. |
| Checkout frontend | **45 passed**, TypeScript/Vite build passed. A synthetic API-token/VITE sentinel was absent from the built browser JavaScript and HTML. |
| Checkout browser | **Eight Chromium E2E tests passed**, covering all seven fixtures plus ambiguous Start retry, explicit approval/resume, persisted refresh and safe projections. Actual API/UI ran on temporary `18020/15175`, scripted investigator with real PostgreSQL in a fresh isolated acceptance schema. |
| Double-charge local acceptance | **482 backend, 65 frontend and two Chromium tests passed**, build/Ruff passed. Includes native PostgreSQL restart, additive migration, concurrent Start claims, immutable receipts, API/Hosted errors and retained browser identity after reload. |
| Fleet and independent rubber-duck | Checkout implementation and independent review were separated. The implementation agent ended before closeout; parent completed test isolation, docs, packaging and acceptance. Review found/fixed the double-charge post-claim error issue; subsequent review reported no significant checkout findings. |
| Packaging and boundaries | Both lane-owned preparation scripts regenerated Hosted copies from canonical source. No dependency upgrades, shared runtime abstraction, private configuration edits, cloud actions, commit or push. Existing normal previews were not restarted. |

Persistent local receipts are session artifacts `pattern-checkout-backend.xml`,
`pattern-dc-backend.xml`, `pattern-dc-ui.log`, `pattern-dc-build.log` and
`pattern-checkout-schema.json`; they are not deployed-release manifests. Local
telemetry tests establish actual span-parent preservation and sanitization, not
new trace presence in Foundry or App Insights.

**Later release gates:** explicitly reviewed source, preservation baseline,
Foundry Deploy and guarded existing-app rollout, Smoke, API/Hosted E2E, native
evaluations, then exact-case Foundry/App Insights ingestion and hierarchy checks.
Double-charge migration 002 must be explicitly applied before its existing-schema
release readiness gate. Checkout schema and business semantics remain unchanged.
The historical deployed API-parent gap below is not claimed fixed in Azure yet.

## 2026-09-17 - Documentation layout and implementation coverage

The initial service-refactor closeout updated the lane README and this ledger,
but did not supply the reference MAF lane's seven-document implementation design.
The parent checkout contract also mixed framework-neutral requirements with
MAF-specific architecture and technology descriptions.

Added independently maintained requirements, business rules with approval,
user flow, 4+1 architecture, stack and source-map documents under `docs/design/`.
Moved this ledger into the same set without removing its history, and repaired
navigation. Parent architecture/stack now describe neutral responsibilities and
point to this lane for implementation details.

The design follows actual checkout source: service-owned synchronous commands
and safe reads, one PostgreSQL authority, pure projections, read-only MAF
investigation and application-owned approval/resume. It explicitly excludes
double-charge-only SSE, history, chat and native checkpoint continuation.
The existing API telemetry parentage limitation and dated release evidence
remain explicit. This is documentation-only; no runtime, dependency, database
or deployment change accompanies it.

## Scope

This ledger records implementation decisions, defects, fixes, and observed
validation evidence for the independent MAF checkout-recovery harness. It is
not a substitute for the framework-neutral domain contract in `../../docs/`.

## 2026-09-17 - Runtime and service-boundary alignment

This release aligns responsibilities with double-charge MAF without importing its
runtime or adding its UI features. Checkout already had service-owned commands
and reads plus pure projections. The requested changes separate configuration,
runtime construction, API composition and transport routes, reuse checkout-owned
wiring in the Hosted adapter, and make query projections service-orchestrated.
Business transactions, approval/evidence binding, retry identities, safe response
contracts and independent framework-state ownership must remain unchanged.

Implementation, independent rubber-duck review and local acceptance are complete.
Deployment and cloud acceptance are **pending** at source freeze. Results below
are dated evidence, not a claim that the refactored source is already deployed.

### Existing environment and preservation baseline

Only checkout PostgreSQL `crmaf-q35uqmuqoh7co-pg` was started from Stopped to
Ready. Local Compose PostgreSQL remained healthy on `127.0.0.1:35432`.
Read-only cloud snapshots recorded **84 cases**, **481 audit events**,
**84 MAF sessions**, **62 remediation records**, **nine approvals** and **two
migrations**, including every primary key and complete migration ledger records.
No reset, deletion or migration was performed.

The existing environment `crmaf-20260912` selected active Hosted Agent **2**.
Its `checkout-telemetry` connection targets the checkout App Insights component
with **`isSharedToAll=false`**. The broader foundation template would set that
value to true; it is deliberately excluded from this application release.

### Release guard changes and lessons

- New `scripts/release.py update-existing` previews or applies only two
  existing Container App image updates. It requires clean exact source, lane
  image digests with matching source tags, locks both tags and manifests, and
  verifies unchanged configuration/identity/environment plus healthy revisions.
  It does not submit the foundation Bicep template, rotate secrets or migrate.
- The business-evidence step now requires `--hosted-report`; it no longer
  silently reads `hosted-e2e-v2.json`. `--output-dir` selects fresh API/business
  receipts so previous release artifacts remain intact.
- `scripts/verify_hosted.py --smoke` permits a pinned one-scenario gate before
  the complete existing seven-scenario matrix.
- Focused release guard validation passed **10 tests**. Full integrated tests,
  independent review and cloud gates were pending at that initial recording;
  subsequent corrections and final local evidence follow.

### Implementation and review closeout

Settings now live in `config.py`; `bootstrap.py` owns construction and explicit
start/close lifecycle. `main.py` and `api/app.py` provide the API factory and
transport lifecycle, with separate dependencies and case/health routers.
Service query methods own safe case/event/artifact projection orchestration.
Pure allowlisted projection functions, business command bodies, transaction
boundaries and native investigation remain unchanged.

The Hosted adapter uses the same checkout-owned runtime factory with explicit
MAF mode, retains thread offloading for synchronous operations, and leaves its
telemetry provider under SDK ownership. Injected services no longer construct
unused repositories/investigators. Startup failures clean up acquired resources.
All affected entrypoints use `checkout_recovery_maf.main:create_app --factory`.
Existing tracked Hosted package copies were regenerated using the lane's
`prepare_hosted.py`; they remain generated copies, not a second implementation.

| Finding | Fix and evidence |
| --- | --- |
| Initial extraction changed development's default execution mode | Restored `scripted`; production still requires explicit MAF, PostgreSQL and API token. Hosted selects MAF explicitly. This is a structural refactor, not a configuration-default change. |
| Rubber duck: apply ignored the actual saved preview | Apply now requires matching source, subscription/group/registry, image identities and app snapshots from the saved preview before any mutation. Missing preview and intervening drift regressions pass. |
| Rubber duck: backend could drift during frontend rollout | Recheck both apps' configuration, image and healthy revision immediately before completion. A simulated backend change during frontend update rejects success. |
| Old evidence path selected Hosted v2 regardless of release | Require the actual Hosted report path and preserve each release's output directory. |

The independent reviewer confirmed both material release findings resolved and
reported no additional significant issues. These guards detect observed drift;
they do not make a two-app rollout globally atomic or prevent later external edits.

### Final local evidence

- **115 backend tests passed**, zero skips, against isolated loopback PostgreSQL,
  including **13 release-guard regressions**. Ruff passed for backend, scripts
  and Hosted entrypoint; Hosted SDK boundary/redaction and evaluation-contract
  scripts passed. Two deprecation warnings were retained, not suppressed.
- Full OpenAPI equality passed against the pre-refactor baseline, canonical
  SHA-256 `e16d83e045dc63c2454acd74577e547da739e5da5d33b7b42c555cef6a5cbd42`.
- **16 frontend tests**, production build and **eight actual browser scenarios**
  passed. No frontend application behavior was changed.
- All **seven local API scenarios** passed with real MAF/Foundry inference and
  PostgreSQL, not merely scripted mode. Separate acceptance ports were
  `18020/15175`; normal double-charge previews were not replaced.
- A fresh real-MAF approval case persisted across an actual API process stop
  and restart. Approval still left it paused; a separate resume produced a
  verified recovery, and repeating resume returned the same safe result.

No Azure application migration or historical-record mutation was used for local
tests. The cloud database baseline remains available for final preservation.

### First deployment attempt and retained failures

Reviewed source `11ecae7dc18b7df6ead814da96a775aa37626e7a` produced active
Hosted **3** and an API image. The remote frontend build `cp3` failed because
ACR's legacy builder rejects the existing Dockerfile's `COPY --chmod`.
Building that unchanged Dockerfile with local BuildKit from an exact Git archive
and pushing the result succeeded. No application-code or Dockerfile workaround
was needed; both failed and successful build receipts are retained.

Hosted v3's first smoke returned a safe failed case rather than the expected
recovery: `5f24a88e-433f-4a52-815f-6b0ca4d2973b`, `harness_failed`, with no
remediation. Read-only reconciliation retained all original 84 cases and found
only this new case. Its **120.291-second** duration matched the unchanged bounded
investigation deadline. Exact trace **`8f2fb1a86f6dcf898cca58b22acd0cbf`** showed
successful initialization, three HTTP-200 model calls, all three diagnostic
reads and workspace write, followed by an unfinished final model request
lasting about 110.8 seconds. This is not evidence of a startup or projection
regression. Its underlying model/service delay is not claimed repaired, and no
timeout, prompt, model, business rule or evaluation threshold was changed.

The old verifier stopped its session on failure and did not retain the safe
result. It now records private command/session identities and safe responses
before acceptance assertions, supplies a fresh idempotent start request UUID,
and retains explicit failed reports. A new regression covers mismatch evidence.
Stopped-session console/system reads returned `stream_interrupted`; they are
retained as unavailable diagnostics, not successful log retrieval.

An independent archive check found local `.venv` files in the uploaded source:
the old `.agentignore` excluded `.foundry` but not local environments. This is a
confirmed packaging defect, **not proof that it caused the model timeout**.
The application image rollout remains held while packaging exclusions and an
exact source/archive validation gate are corrected. No old version, failed case,
session or receipt was deleted.

The packaging correction excludes local environments/private configuration/caches
and adds `prepare_hosted.verify_code_archive`: exact canonical file set,
service SHA-256, file bytes, duplicate-entry and symlink checks. **32 synthetic
archive regressions** reject sentinel private files, altered/missing source and
invalid archives. The complete corrected suite passed **148 tests, zero skips**,
with Ruff, Hosted SDK boundaries and evaluation-contract checks also passing.
The independent reviewer found no significant issues in these new corrections.
Actual downloaded-source verification is required for the replacement release;
unit tests alone do not establish that the uploaded archive is clean.

Replacement Hosted **4**, deployed from `38d24df`, passed its fresh pinned smoke.
Its downloaded ZIP contains **48 canonical files**, no local environment, and
matches platform SHA-256
`c022380336a7b4f4fc81b6c0d4783443ac82336b3d79be8e118d7f06233ae1bc`.
The first archive check exposed a verifier-only omission: tracked root
`eval.yaml` was not in its canonical list. Requiring that exact file, with
missing/changed/unexpected-YAML regressions, corrected the gate without changing
the deployed source or requiring another Hosted version. All **151 backend
tests** and Ruff pass. Runtime/environment and actual archive readback pass;
the broader API/UI rollout and cloud matrix remain subsequent gates.

Hosted v4's E2E verified five fixtures before the local azd credential subprocess
was killed while obtaining the sixth request's token. PostgreSQL reconciliation
confirmed that request UUID had **not** created a case. Credentials were
rechecked without printing tokens; the exact pending UUID was reused, followed
by only the seventh fixture. The combined evidence now covers all seven;
the interrupted report and command journal remain separate and retained.

The image-only guard then correctly stopped after the API update because Azure
CLI serialized three secret-backed environment entries with `value: ""` instead
of `value: null`. The secret references and effective settings were unchanged;
the API revision was healthy, and the frontend had not been updated. The
comparator now normalizes only absent/null/empty unused values when `secretRef`
is present. Changed references and nonempty literal values remain drift errors,
covered by regressions. The saved partial rollout is reconciled explicitly,
not replayed or silently marked successful.

### Final deployment and acceptance

The partial image rollout was reconciled from its saved proposal. A read-only
source comparison proved only release tooling, its tests and this ledger had
changed since the image build; application build inputs were unchanged. Both
tag and manifest locks were reverified before updating **only** the remaining
frontend. Final readback verified both images, healthy ready revisions and
unchanged effective configuration, identities, environment and secret references.

| Surface | Accepted identity |
| --- | --- |
| API/UI image source | `9c2d7ff49bfa6b0db1b322d886e3033bf4a2c914` |
| Reconciliation tooling | `0364b921c55937cf00fcdf2a3ca776bc43a9ed35` |
| Hosted | `checkout-recovery-maf:4`, packaged from `38d24df`; package unchanged at image source |
| API revision | `crmaf-q35uqmuqoh7co-api--0000001` |
| UI revision | `crmaf-q35uqmuqoh7co-web--0000002` |
| API digest | `sha256:b87ef7ad603021398aa474d4fd49c9ace126040016750c676d87e78ecc14f579` |
| UI digest | `sha256:2683688904cfa18f1596afa342287064ae895fc73795be7adff0c2e7e0f977e0` |

Final local acceptance passed **153 backend tests, zero skips**, **16 frontend
tests**, frontend production build, Ruff, Hosted-boundary and evaluation-contract
checks. The earlier live local acceptance additionally passed seven real-MAF
API scenarios, eight browser scenarios and the real-process approval
pause/restart/resume/idempotent-retry check. No runtime code changed afterward.

Fresh cloud acceptance passed authenticated UI/API smoke (including all three
service-owned case/audit/workspace queries), Hosted smoke, **7 API + 7 Hosted
E2E scenarios**, **8 browser tests**, and independent PostgreSQL business,
approval, remediation, audit and framework-session checks for all **14 E2E
cases**. The explicit command boundary remains intact: approval does not resume,
and approval-required evaluation cases remain paused.

The unchanged native Python evaluation group
`eval_188058e6d7424429b855697f94735630`, run
`evalrun_589414300c88442ab76ad8af8c924db3`, passed **7/7** with numeric score
**1.0**, explicit `passed: true`, and a separate exact-contract comparison for
every output item. Grader source and threshold were verified before reuse.
All output items were downloaded; metadata preserves the previous accepted v2
run and older failed diagnostic experiments. Native Python results have no
prose judge reason; that is not a missing score or a substituted LLM judgment.

### Telemetry verification and retained limitation

Exact case correlations verified **15/15** fresh smoke/E2E starts, associated
harness/model spans, **8/8 Hosted v4 identities**, and **386 request/dependency
spans** with sampling weight one. Hosted internal parent chains are complete.
Example smoke operation: **`7a2e3b03b1e9665f1ef008e644b3ffd0`**.
The top server spans reference upstream platform/client parents outside this
application export; they are transport boundaries, not missing internal steps.

**Full API hierarchy acceptance is not claimed.** The existing content-safe API
exporter retains application tool spans but drops their intermediate framework
parents: three missing internal parent spans per API case, **21** across the
seven cases. Read-only queries of three pre-refactor operations confirmed the
same three gaps. This is a documented pre-existing observability limitation,
not a service-refactor regression; telemetry behavior was intentionally
preserved rather than expanding this change into an exporter redesign.

Scoped checks across requests, dependencies, traces and exceptions found **zero**
prohibited message/tool-content attributes or credential text. The Foundry
`checkout-telemetry` connection still targets App Insights
`crmaf-q35uqmuqoh7co-appi` (app ID
`09b81019-3462-4b1e-b934-b248d0679447`), with sharing **false**. This is
programmatic verification of the Foundry-linked telemetry store, not a claim
that both portal screens were manually inspected.

### Preservation and lessons

Every original primary key and both full migration records were retained.
Final storage contains **116 cases, 670 audit events, 115 framework sessions,
85 remediation records and 15 approvals**, with **2 unchanged migrations**.
All **11 original Azure resource IDs**, the monitoring target and sharing
setting remain unchanged. No foundation template, schema reset, secret rotation,
historical cleanup, timeout increase or business-rule change was used.

Keep canonical upload verification separate from runtime smoke: a successful
upload can contain unintended local files, and removing them does not prove a
model-latency incident's cause. Preserve command identities before invoking and
reconcile ambiguous failures instead of creating replacement business commands.
Normalize only proven serialization equivalents in release comparisons, and
retain evidence when a multi-app rollout pauses. Distinguish trace presence,
complete internal parentage and deliberate content filtering; baseline evidence
is required before calling a gap pre-existing.

Private receipts are under the session evidence directory
`release-20260916-workspace/checkout-service-20260917`, including the original
failed attempts, corrected acceptance, exact KQL, all evaluation items, and
before/after storage/resource snapshots. Temporary acceptance processes were
stopped; existing previews and databases were not removed. Double-charge MAF,
LangGraph and canonical `shared/` remain unchanged by this checkout refactor.

Private evidence is retained in session
`78c6c3f4-5e02-4c4f-93a4-068df29dc2aa`,
`files/release-20260916-workspace/checkout-service-20260917/`.

## Initial decisions (historical)

| Decision | Reason |
| --- | --- |
| MAF Harness Agent | Demonstrates Article 3 harness primitives while preserving application-owned business authority. |
| Foundry Hosted Agent | Hosts the same explicit command service; it is the runtime, not a replacement for PostgreSQL authority. |
| Read-only-first tool policy | Establishes adaptive diagnosis before introducing consequential actions. |
| Explicit approval and resume | Prevents chat or model output from authorizing a customer-impacting remediation. |

## Validation evidence

| Date | Change | Evidence | Result |
| --- | --- | --- | --- |
| 2026-09-12 | Framework-neutral checkout contracts and simulators | `uv run --extra test pytest` from `shared/` | Passed: 25 tests |
| 2026-09-12 | MAF application, API, and hosted-agent adapter | Backend unit tests, Ruff, hosted-agent compilation | Passed: 14 tests; source and hosted adapter lint/compile checks passed |
| 2026-09-12 | Independent React UI | Vitest and production build | Passed: 7 tests; TypeScript/Vite production build passed |
| 2026-09-12 | Evaluation contract | `uv run python scripts/verify_evals.py` | Passed: all seven fixtures match the delivery and hosted evaluation contracts |
| 2026-09-12 | Isolated infrastructure definition | `az bicep build --file infra/main.bicep` | Compiled successfully; existing Bicep linter advisory warnings remain |
| 2026-09-12 | Disposable PostgreSQL integration | Migration apply/check plus `scripts/e2e.py` | Passed: all seven explicit-command API scenarios completed with the expected terminal status |
| 2026-09-12 | Approval durability | Approval, process restart, and explicit resume against disposable PostgreSQL | Passed: recovered status and authoritative verification persisted across restart |

## Defects found and fixed

| Date | Defect | Fix | Regression evidence |
| --- | --- | --- | --- |
| 2026-09-12 | Checkout business state lived only in a process-local simulator, so approval/resume could fail after restart or on another replica. | Persisted a typed checkout simulator snapshot inside the authoritative case state and rehydrate it for every remediation/verification operation. | Restart-safe PostgreSQL approval/resume E2E passed. |
| 2026-09-12 | A matching retry of a durable approval command was rejected as a conflict. | Matching decision/reviewer retries now return the recorded case; conflicting retries remain rejected. | Backend unit tests cover matching and conflicting retries. |
| 2026-09-12 | Automatic inventory recovery had no configured safe bound despite the documented policy. | Added `max_auto_inventory_quantity`, defaulting to one, to the application and deployment configuration; larger reservations route to manual review. | Backend unit test covers the manual-review branch. |
| 2026-09-12 | PostgreSQL deserialized the remediation operation UUID as a UUID object while the internal contract requires a string. | Normalized `operation_id` to text at the repository read boundary. | Disposable PostgreSQL API E2E passed. |

## Open items

The initial evidence above is historical foundation evidence, not proof of a
live harness. The following release record supersedes its original limitations.
All planned educational-demo delivery gates below are complete, including
deployed business flows, browser flows, native Foundry evaluation, and telemetry.
Production hardening remains explicitly outside this acceptance boundary.

## Live-harness release - 2026-09-12

| Gate | Observed evidence |
| --- | --- |
| Real MAF integration | `MafInvestigator` calls the new Foundry model through `create_harness_agent`; scripted mode is explicit and forbidden in production. |
| Python and PostgreSQL regression | 56 tests passed with a dedicated PostgreSQL URL, including rollback, repeat fixtures, approval retry after closure, concurrent resume, tool selection, and telemetry redaction. |
| Local live API | Seven scenarios passed all shared normalized outcome fields using real Foundry inference and persisted PostgreSQL state. |
| Local UI | 16 unit tests and production build passed; eight Playwright scenarios passed against the live API in 2.1 minutes. |
| Containers | Non-root backend build/import/readiness/token/recovery checks passed; nginx build, health, login, and unauthorized denial passed. |
| Local Hosted Agent | Responses 2.0 invocation exercised real MAF and verified recovery. Actual Hosted SDK imports and sanitized unknown-fixture/database-error boundaries passed. |
| IaC and deployment | New Foundry environment provisioned after preview; application foundation and immutable API/UI image deployment applied through Bicep; migrations 001 and 002 applied explicitly. |
| Hosted v2 | All seven explicit start/approval/resume scenarios passed complete outcome comparisons. Owned verification sessions were stopped afterward. |
| Deployed API | Seven full-outcome scenarios passed through the authenticated public UI's private API proxy. |
| Deployed browser | All eight Chromium scenarios passed in 1.6 minutes, including refresh persistence, safe projections, separate approval/resume, and ambiguous-response retry identity. |
| Business evidence | Fourteen API/Hosted cases independently re-read from Azure PostgreSQL; final evidence, intent identities, one remediation, approvals, audit counts, and separate workspace state matched. |
| Telemetry | Both API and Hosted roles emitted actual `checkout.harness`, `checkout.model`, diagnostic tool, approval, remediation, resume, and verification spans. API requests and platform Hosted `invoke_agent` requests were present. |
| Redaction sample | Two-hour query examined 3,763 Hosted rows, 423 API rows, and 45 platform request rows: zero selected forbidden content attributes and zero DSN/canary text matches. This is scoped evidence, not a universal proof of absence. |
| Native Foundry evaluation | Seven Hosted Agent v2 start scenarios passed with numeric score 1.0 each, threshold 1.0, and independent strict JSON-contract comparison. Approval scenarios correctly paused instead of auto-approving. |
| Evaluation regressions | 24 tests passed for supported response namespaces, missing/null fields, scalar types, invalid expectations, extra content, and missing/partial/invalid cloud scores. |
| Final closeout | Lane Ruff and dataset consistency passed; public health returned `ready`, anonymous UI access returned 401. Owned local API and disposable PostgreSQL processes stopped; deployed services and Azure business state retained. |

### Actual deployed resources

- Environment/resource group: `crmaf-20260912` / `rg-crmaf-20260912`, `northcentralus`.
- Foundry account/project: `cog-5qu6hroatjn54` / `crmaf-20260912`.
- Hosted Agent: `checkout-recovery-maf:2`, Python 3.13, Responses 2.0, 1 CPU/2 GiB.
- Model: `gpt-4.1-mini`, version `2025-04-14`, Standard capacity 100.
  GlobalStandard quota was already allocated; no other project's allocation was changed.
- PostgreSQL: `crmaf-q35uqmuqoh7co-pg`, database `checkout_recovery`.
- Registry: `crmafq35uqmuqoh7coacr`; remote API build `cp1`.
- API image: `checkout-recovery-maf-api@sha256:c4dc53e0b01fe47dee348f69300eec0f8d46e555ed70a3fa890134f191992c14`.
- UI image: `checkout-recovery-maf-web@sha256:d1a07fcf8216f1ca10743c752dd353088c45cc52e24e12c954e0fc9976bae2a4`.
- App Insights: `crmaf-q35uqmuqoh7co-appi`.
- UI: <https://crmaf-q35uqmuqoh7co-web.icymoss-074cbdaa.northcentralus.azurecontainerapps.io>.

Generated secrets and API/Hosted/business acceptance JSON are retained in ignored
`.azure/crmaf-20260912/`. Retrieve the UI login from `release-secrets.json`;
never paste that file into an issue, trace, or commit.

### Additional defects and lessons

| Finding | Correction and evidence |
| --- | --- |
| Initial factory was never invoked | Replaced the idle integration with actual bounded MAF execution in API and Hosted paths; live results require `harness_mode=maf`. |
| Repeated fixture targets collided globally | Generate case-specific order/payment/reservation identities. A supplied start UUID identifies a retry, not a new fixture run. Repeated runs now pass without dropping state. |
| Approval and audit writes were not atomic | Command-scoped transactions plus per-case PostgreSQL advisory locks; memory adapter rolls back snapshots. Concurrent resumes yield one remediation. |
| Approval lacked request/evidence binding | Server-issued approval request ID, run/evidence hash, reviewer/reason, immutable decision, and explicit resume. Matching terminal retries remain valid. |
| Optional log reads consumed the failure fixture | Read diagnostics from an isolated snapshot; the authoritative application read still observes the intended failure. |
| Workspace and client API assumptions | Workspace read/write are async, paths are relative, and the native write tool is `file_access_write`. `default_options` belongs on the harness factory, not `FoundryChatClient`. |
| Framework history ownership warning | Set `store=false`; persist private MAF session/workspace separately from business state. Browser projections expose metadata only. |
| Rubber Duck: recovery could reverse cancellation | Require failed checkout, authorized payment, and expired reservation at diagnosis and mutation boundaries; equivalent idempotent retries are checked first. Four adverse-state regression cases passed. |
| Rubber Duck: unknown Hosted fixture leaked raw input through KeyError | Sanitize invalid commands; replace database exceptions with a fixed unchained error. The actual SDK boundary regression checks exception text and logs. |
| Package downloads failed inside local Docker | Official uv with Microsoft's HTTPS package mirror resolved transport failures without disabling TLS. `--no-sources` avoids broken editable shared-package references. ACR build also passed against the normal index. |
| azd model capacity rejected interpolation | Keep typed model/version/SKU/capacity values in `azure.yaml`; integer capacity cannot be an unresolved string placeholder. |
| azd returned endpoint under a different output name | Explicitly bound the returned project endpoint to the Hosted service's expected environment variable. No endpoint was guessed. |
| Hosted verifier combined incompatible CLI flags | Pin the version when creating a session, then invoke using only that session ID. The initial failures were CLI argument rejection, not cold starts. |
| CLI update warning followed the raw JSON body | Parse one complete JSON response and permit only the recognized trailing CLI warning; reject unrelated trailing data. |
| UI ingress expected port 80 but nginx listened on 8080 | Corrected Bicep ingress and added `/healthz` readiness on 8080; reran public API and browser acceptance. |
| Browser runner used a different browser cache | Installed the missing pinned Chromium executable; completed deployed browser E2E. The original local runner used `PLAYWRIGHT_BROWSERS_PATH=0`. |
| Old eval checker assumed start-only and full command datasets were identical | Validate the derived start dataset separately: approval scenarios must remain paused; the full command runner alone submits approvals/resumes. |
| Cloud code evaluators returned zero despite correct agent outputs | A one-case native Python diagnostic proved that code executes but receives the response in `item["sample.output_text"]`, not `sample["output_text"]` or `item["response"]`. Support the observed Foundry namespace alongside the normal/native and mapped-local namespaces. The corrected native evaluation passed all seven cases without changing thresholds. |
| Supplemental prompt judges returned invalid/missing numeric results | Catalog-normalized version 5 also failed. Retained the failed artifacts and diagnostic registration script; replaced this unproven release path with the verified native deterministic grader. The prompt-judge parser failure itself is not claimed fixed. |
| Exact comparison could confuse absent/null or numeric/boolean values | Require expected keys to exist with matching JSON scalar types; reject empty/invalid expectations. All cloud criteria must return an explicit pass and numeric 1.0. Regression tests reject null scores and mixed valid/missing criteria. |

### Evaluation and evidence locations

`infra/foundry-hosted/agent/.foundry/agent-metadata.yaml` tracks the selected
environment, registered evaluator versions, and latest evaluation IDs.
Every attempted cloud run's full output items are retained under that agent's
`.foundry/results/`. Failed grader runs are historical failures, not successful
agent evaluations. `scripts/collect_evaluation.py` requires both valid cloud
scores and exact JSON comparison; null scores do not pass.

The accepted native evaluation is
`eval_188058e6d7424429b855697f94735630`, run
`evalrun_2d6557a7f2f54c1dbef6f204e5fe2d48`, against Hosted Agent version 2.
Every one of its seven output items returned `passed=true`, `score=1.0`,
and passed the independent exact comparison. The catalog identity is
`checkout_exact_contract:2`; its native evaluation group embeds the grader
source and does not need an LLM judge.

`scripts/register_native_evaluation.py` registers the matching catalog identity
and creates that native Python evaluation-group shape from `evals/start_contract.py`.
The namespace diagnostic
`eval_19a6963d6f024460af1affdf0623b4c9` /
`evalrun_e188dea5ef5d4265870839ebb9069122` was deliberately nongating: a
constant execution control and a numeric argument-key mask exposed no content.
Its diagnostic score is not a business evaluation pass.

Raw evaluation artifacts and generated grader definitions are ignored locally;
the acceptance summary and selected run/version identifiers are versioned.
No failed artifact was deleted or relabeled. Runtime business source did not
change during the evaluator fix, so Hosted Agent v2 and the accepted API image
remain the reviewed deployment.

Use `observability/acceptance.kql` and `observability/redaction.kql` for scoped
telemetry acceptance. PostgreSQL verification uses `scripts/release.py evidence`.

### Intentional boundaries, not completed production hardening

Payments and inventory are deterministic simulators persisted in PostgreSQL,
not external merchant systems. Database transactions therefore protect this
simulation; they cannot provide exactly-once behavior for a real remote payment
API. Basic-auth demo users supply reviewer labels; production requires independently
verified reviewer identity and downstream authorization. PostgreSQL currently
uses password authentication with an Azure-services firewall exception plus
operator access. Shell/browser agent tools are disabled. Workspace/session state
is persisted, but recovery does not resume a partially executed model loop.
