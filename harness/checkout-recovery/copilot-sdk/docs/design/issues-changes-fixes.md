# Issues, changes, fixes and learnings

## 2026-09-20: public demo access and polling trace cleanup

**API/UI deployed; anonymous smoke, seven original API scenarios and eight
browser tests passed.** Browser Basic login is temporarily off by default.
Set the frontend `CHECKOUT_UI_AUTH_ENABLED=true` to restore it with the existing
htpasswd secret. Anyone with the UI URL can issue demo commands; reviewer labels
are not verified identities. Private API ingress/token checks, Azure identities,
explicit business approval and upstream TLS remain intact.

Successful GET/HEAD/OPTIONS API spans are suppressed at export. Command roots,
native model/tool spans and failed requests remain; handled HTTP errors now carry
error status. Historical telemetry is retained. **51 focused backend tests**
passed against current source with cloud dependencies. Real nginx containers
verified anonymous access, opt-in login and token privacy.

| Release evidence | Result |
| --- | --- |
| API | `crcopilot-xfvhibddvclsw-api--0000001`; digest `sha256:d38ac2d6db750e8152bca564a371091b719af4b2b4a5d3ca33f431612e887416` |
| UI | `crcopilot-xfvhibddvclsw-web--0000001`; digest `sha256:be6ca3238f9af2a9c1d28e214918765c0aff54f3dba71dac29cb7f3666486a0d` |
| Image provenance | Immutable prior image plus two hashed source-file replacements per image; tags `access-noise-dc870ce04a5196b0` / `access-noise-7441a7a01fe9e1e5`, with tags and manifests locked. Cloud dependency pins and native runtime unchanged. |
| Fresh App Insights check | After 20 successful polling probes: **zero successful non-command API roots**, 25 workflow command roots, the intentional 404 probe retained, 216 model spans and 302 tool spans. Counts are spans, not logical invocations. |
| Preservation | Exact image-only configuration/identity comparison passed. No infrastructure provisioning, migrations, data deletion or new evaluations. Hosted **v3** remains active and unchanged; this patch affects API/UI behavior only. |

Local DNS interrupted the original approved case's Resume request. Its persisted
state and original case/request IDs were reconciled before continuing; no
replacement acceptance cases were silently created. Test-only DNS overrides used
Azure-verified ingress IPs and retained normal hostname/TLS verification, without
changing application code or system DNS. The first browser attempt selected an
absent lane-local cache; the existing default cache passed all eight tests without
installing or upgrading packages. Original failure receipts are retained.

Azure consumes standard HTTP method metadata and returns `success` as text:
classify API roots through command trace IDs and normalize success, rather than
assuming a missing custom method means polling. Private receipts are retained
under the session's `files/access-noise/copilot-sdk/`; the UI URL is unchanged.

## 2026-09-20: independent Copilot lane started

**Status:** separate laptop/cloud profiles are implemented and independently
reviewed. Cloud public-PyPI pins include urllib3 2.8.0; local mirror files remain
unchanged. Cloud-profile acceptance passed 440 backend tests, Ruff and exact native
Hosted package verification. **Cloud rollout and acceptance are complete:** own
API/UI, PostgreSQL and Foundry Hosted v3 in `rg-crcopilot-20260920`, using
gpt-4.1-mini Standard100. Final backend acceptance passed 453 tests; remote
E2E, evaluations, native container-replacement restore and trace verification are
recorded below. Earlier mirror release-hold entries are historical, not a
restriction on cloud package sources.

### Scope

Preserve checkout business behavior, explicit Start/Approval/Resume, safe UI
projections and PostgreSQL authority. Configure the native Copilot harness rather
than importing MAF or creating another conversation-history engine.

### Evidence and lessons carried forward

- The separate POC demonstrated Azure-model BYOK with a refreshing Entra token
  provider, Foundry Responses hosting and readable native telemetry. Those results
  are not this lane's acceptance.
- Managed harness behavior is separate from hosted-compute durability. Native
  sessions need tested persistence and restoration; a session ID alone is not
  a durable checkpoint.
- MAF business Resume reads durable business state, not its stored conversation.
  Preserve that independence here even when native conversations can resume.
- Native request/response/tool-handler spans can represent the same logical
  execution. Count response/tool-call identities, not raw spans.
- A prior MAF acceptance matrix had one incomplete final trace. Flush timing was
  suspected, not proven. This lane must verify original-case trace ingestion
  before stopping test sessions; supplementary cases do not erase failures.
- Fixture-content telemetry is explicit opt-in; never export credentials, hidden
  reasoning, unrestricted prompts, reviewer text or native session dumps.

### Implementation decisions

- Independent package `checkout_recovery_copilot`, with integration under `sdk/`.
- Native session persistence will use SDK-owned files without reconstructing
  messages; choose the smallest storage integration that passes restart tests.
- Existing MAF, POC, databases and deployments remain untouched.

### Local business/UI gates completed

- Created an independent PostgreSQL Compose stack on loopback `45432`; did not
  reset, migrate or restart any existing lane database.
- Preserved the exact business OpenAPI schema. Its fingerprint matches the MAF
  baseline after normalizing only the intentional application title.
- Backend business/API/configuration/durability selection: 75 passed against
  the dedicated database, including private framework-state readback and business
  Resume with an unavailable investigator.
- Frontend: 45 tests and production build passed. Scripted local API matrix:
  seven of seven; Chromium workspace matrix: eight of eight.
- Native telemetry bridge and application telemetry selection: 35 passed,
  including trace-parent preservation, content filtering, malformed-batch
  reporting, independent receiver sockets and private local receipts.

These are scripted business/UI and telemetry-component checks, not real Copilot
inference or deployed acceptance. The live SDK/restore gate remains in progress.

### Integration issues discovered

- A copied OpenAPI fingerprint initially failed because of the new harness title.
  The parity test now checks the Copilot title explicitly and compares the
  normalized business schema to the unchanged baseline fingerprint.
- The copied database evidence verifier expected a native plan even in explicitly
  scripted tests. Separate scripted evidence from the default real-harness gate;
  do not weaken cloud requirements to make scripted runs appear native.
- Runtime construction initially preceded completion of the SDK investigator's
  new telemetry keyword arguments. Resolve the interface before full acceptance;
  do not remove telemetry settings or hide construction errors.
- Read-only model preflight found `Standard` gpt-4.1-mini quota available in
  northcentralus while `GlobalStandard` was exhausted. Preserve the comparison
  model/SKU rather than reallocating another deployment's quota.

### Native SDK and integrated local evidence

- Initial evidence used SDK 1.0.14 / runtime 1.0.85 / protocol 3. Native CLI is packaged separately
  from private per-case state and starts offline; no runtime download in an
  investigation.
- Native skills, required diagnostics, bounded workspace and optional inventory
  child were observed executing, not inferred from model text.
- Fresh Python/CLI processes restored native history and recalled a synthetic
  marker absent from the second prompt, using the existing Azure comparison model
  for inference only. The temporary raw archive was removed.
- Runtime 1.0.85 initially sent unsupported `reasoning.effort` to gpt-4.1-mini.
  Supported provider `model_id`/`wire_model` separation fixed the behavior profile
  without changing the actual Azure deployment. Both identities are distinct
  telemetry metadata; no model substitution is claimed.
- Native archive validation is shared by restore and private PostgreSQL auditing.
  Audit requires native files, bounded actual plan and observed tool/skill flags.
  Scripted auditing remains an explicit different mode.
- Real Copilot API matrix: seven of seven. PostgreSQL business/audit/intent and
  native-session evidence: seven of seven.
- Real Copilot Chromium matrix: eight of eight. Its complete local command traces
  contain 3,067 span records across 14 command traces, 27 safe diagnostic-content
  records, 61 distinct model-response identities, and zero internal missing-parent
  edges. These are local receipts, not App Insights ingestion evidence.
- Integrated backend selection reached 322 passing tests against the new database.
  Full source verification is repeated after review fixes; this count is a dated
  intermediate receipt, not a permanent target.
- Native context compaction is enabled at runtime defaults but has not been
  explicitly observed. Model-turn budget is monitored cancellation, not a hard
  pre-request request/cost cap; tool execution is bounded separately.

Local Hosted HTTP acceptance and independent Rubber Duck review remain in
progress. Foundry preview proposes only the new resource group/account/project
and Standard model deployment; no cloud resources have been applied yet.

### Review hardening in progress

- Kept readable workspace/delegation handler names, stabilized model span names,
  and labeled configured deployment separately from observed model metadata.
- Serialized local receipt writes, handled short writes, capped each file at
  32 MiB and made write failure explicit. Appending the application suffix to the
  whole filename avoids collisions. Production refuses local receipt files.
- Kept strict native archive completion: failing before remediation is deliberate
  when required conversation durability cannot be established. A best-effort
  archive would silently weaken the agreed capability; business Resume remains
  independent of the archive.
- Made existing pool bounds explicit and documented the long Start transaction's
  concurrency limit; did not replace command atomicity with an unreviewed
  two-phase workflow.
- API tracing has one provider per process lifetime. Restarting a Runtime inside
  the same process is not a supported telemetry reset.
- Two first Docker attempts failed and remain distinct receipts: API dependency
  installation needs diagnosis; UI used the wrong context root. Both images must
  build and start successfully before cloud deployment.
- SDK review fixes include inventory-only child permissions, safe proxy/CA
  passthrough, private restored-plan permissions, primary-error-preserving cleanup,
  separate turn/retry accounting, and explicit post-drain telemetry failure
  evidence. Archive rejection logs a fixed reason code without session content.
- Hosted cancellation now cooperatively interrupts read-only investigation and
  waits for durable failed-Start persistence and native-process exit. Accepted
  Approval/Resume commands finish atomically rather than cancelling a side effect.
- Runtime now records configured harness identity before investigation, so a
  failed native Start no longer falsely appears scripted. A closed harness
  failure requires a new Start UUID after repair; Resume cannot reopen it.
- Latest integrated isolated-PostgreSQL run: 364 backend tests and Ruff passed.
  Independent follow-up review and container/Hosted acceptance still gate rollout.
- The existing MAF ledger identifies approved Microsoft PyPI/npm mirrors for
  laptop/container dependency download failures. Keep TLS and pinned versions;
  do not force the mirror into Foundry remote builds, where prior MAF evidence
  showed a different dependency-resolution failure.

### Approved-feed dependency trial

The API Docker build failed on public PyPI TLS. The Microsoft feed fixes that
transport issue but does not yet provide the originally selected SDK `1.0.14`.
The approved `1.0.13` wheel matches official source and exposes all harness-used
APIs. Its default runtime is `1.0.83`; this lane deliberately retains an explicit
`1.0.85` runtime/protocol `3`, requiring actual pair verification rather than
assuming the SDK default is the selected binary.

Switching the lock to the approved feed also selected older available versions
of thirteen other dependencies. A version-diff guard exposed this before install.
The feed-aligned set is an explicit candidate under the existing version bounds,
not an SDK-only change or a silent fallback:

| Package | Original | Approved-feed candidate |
| --- | --- | --- |
| github-copilot-sdk | 1.0.14 | 1.0.13 |
| httpcore2 / httpx2 | 2.13.0 | 2.12.0 |
| idna | 3.20 | 3.19 |
| multidict | 6.9.0 | 6.8.0 |
| openai | 3.16.2 | 3.16.1 |
| propcache | 0.5.4 | 0.5.2 |
| protobuf | 7.36.2 | 7.36.1 |
| psycopg / psycopg-binary | 3.3.6 | 3.3.5 |
| psycopg-pool | 3.3.2 | 3.3.1 |
| ruff | 0.16.8 | 0.16.7 |
| urllib3 | 2.8.0 | 2.7.0 |
| uvicorn | 0.53.0 | 0.52.4 |

Frozen installation and the initial 146 business/configuration/telemetry tests
passed. Earlier receipts remain SDK `1.0.14` evidence; old native archives were not
converted or relabeled.

### Final local functional results for the feed-aligned candidate

| Gate | Result |
| --- | --- |
| Backend, isolated PostgreSQL, lint | 385 passed; Ruff clean |
| Frontend | 45 tests and production build passed |
| Real Copilot API | 7/7; strict PostgreSQL/native-state audit 7/7 |
| Real local Responses HTTP | 7/7; 11 successful commands; strict native/database audit 7/7 |
| Browser workflow | 8/8, including ambiguous Start replay |
| Native memory/lifecycle | Real Azure fresh-process create/resume, delegation and marker recall passed; cancellation/permissions/budgets/protocol/timeout probes passed |
| Container packaging | API and UI builds/startup/authentication passed; actual non-root API runtime verified as 1.0.85/protocol 3 |
| Local trace graph | 3,415 unique spans, 25 command traces, 48 allowed diagnostic records, 98 distinct model responses, zero missing internal parents |
| Independent review | Application/native/packaging fixes accepted; dependency security hold below remains |

Evidence is under ignored `.acceptance/sdk-1.0.13/`, with UI image receipts in
`.acceptance/ui-image-approved-feed/`. The API image ID is
`sha256:3ae9625980cdef8c3eedf5d3db8ff2a526b2f7f89517c3553c1ad7a610614110`.
These are **local** results, not Foundry deployment, cloud evaluations or
App Insights ingestion. Compaction remains enabled but not explicitly exercised.
Adversarial cancellation/permission/budget/protocol/timeout probes used the real
native runtime with a local scripted Responses peer; they are separate from the
real Azure create/restore and command E2E results.

### Release hold: urllib3 security fixes absent from the approved feed

The [official urllib3 2.8.0 release](https://github.com/urllib3/urllib3/releases/tag/2.8.0)
and [upstream changelog](https://urllib3.readthedocs.io/en/stable/changelog.html)
identify three fixes omitted by the feed-selected `2.7.0`:

| Advisory | Upstream severity | Issue |
| --- | --- | --- |
| GHSA-8988-9cw3-xx77 | High | HTTPS proxy TLS configuration may be ignored or overridden |
| GHSA-vxq7-64xx-v4gw | High | Unbounded chunk-size-line buffering |
| GHSA-gh4c-6fx4-qh6g | Medium | Chunked Deflate streaming infinite loop |

The global GitHub advisory API returned 404/empty results, but the official release
and changelog independently confirm the fixes. Do not interpret that API lag as
absence of the issue. The native Node runtime does not use urllib3; Python-side
credential/telemetry dependencies do. Local functional success does not establish
that the affected paths are safe.

A fresh approved-feed index check still exposes only `2.7.0`. No risk waiver,
TLS bypass, public-source fallback or cloud deployment was performed. The user was
unavailable to authorize a narrowly scoped official-PyPI exception, so release
remains blocked. Resolve by making `urllib3>=2.8.0` available through an authorized
source, enforcing that minimum, refreshing the lock/artifacts and rerunning affected
gates before any provision/deploy. The fourteen-version diff is arithmetic evidence,
not a blanket security approval of dependency downgrades.

The reviewed Foundry preview still proposes only the new resource group, account,
project and Standard model. Original lanes, POC and cloud resources are unchanged.
Owned acceptance API/UI and test containers were stopped; the new local PostgreSQL
database and all business records/evidence remain available. No commit or push.

### Fleet follow-up: approved-source investigation

The independent source-resolution task found no documented alternative Python
feed in the repository. A fresh check at `2026-09-20T17:49:48Z` still lists
`2.7.0` as the configured Microsoft feed's newest urllib3 release. The structured
receipt and index snapshot are retained under `.acceptance/feed-resolution/`.
This does not establish that no other Microsoft mirror exists; it means no usable
authorized alternative was established by this investigation. The source blocker
therefore remains, independently of the release-guard implementation underway.

### Fleet follow-up: release hold enforced in tooling

`scripts/verify_release_dependencies.py` now rejects missing, vulnerable,
prerelease, ambiguous or mismatched urllib3 candidates. It requires a stable
version at least `2.8.0`, comparing the lock with exported requirements and the
installed build environment where applicable. A patched developer environment
cannot make a vulnerable artifact lock pass.

The check is wired into release commands, Hosted preparation/archive verification,
the azd prepackage hook and the API Docker build. Rejection occurs before cloud
commands, dependency installation or native-runtime download at the relevant
entrypoint. The current `2.7.0` candidate was rejected by the script entrypoints
and an offline Docker build; this is the expected safety result, not a successful
release build. Receipts are under `.acceptance/release-dependency-gate/`.

The integrated suite now passes **428 tests**, with Ruff clean. Previous images
and local E2E receipts remain evidence for the earlier functional candidate, not
deployable artifacts that bypass the new guard. Package versions, sources and
cloud resources were not changed by this Fleet follow-up. Approved patched-package
availability still blocks deployment and all remote acceptance gates.

### Correction: laptop download limits were incorrectly applied to cloud builds

**Root cause:** local Docker downloads from public PyPI failed TLS checks. I
incorrectly treated the suggested Microsoft mirror workaround as a restriction
on the cloud dependency set too. This selected older packages and created an
avoidable production dependency problem. No Foundry-side download restriction
had been demonstrated.

**Proven approach:** the ignored POC uploads code and requirements to Foundry
with `dependencyResolution: remote_build`, without a Microsoft index override.
Its recorded resolved dependencies include Copilot SDK `1.0.14` and urllib3
`2.8.0`. The earlier MAF ledger also records successful public-PyPI resolution
in Foundry after removing a hosted-only mirror override.

**Approved correction:** keep laptop mirror settings and local pins separate
from secure, pinned public-PyPI cloud dependencies. Validate the cloud set
independently, retain the patched-package release checks, and let Foundry install
the uploaded requirements remotely. Separate versions are permitted; local results
alone do not validate a different cloud dependency set.

**Learning:** a laptop workaround must not silently determine production versions
or become an invented cloud-source restriction. The authorized correction was
subsequently deployed and verified below. The POC remains unchanged.

### Cloud release: separate profiles, Hosted v3 and actual acceptance

**Dependency correction:** the laptop `pyproject.toml`, `uv.lock` and `.venv`
were preserved. `requirements-cloud.lock`, `requirements-cloud-dev.lock` and
`dependency-profiles.json` freeze the public-PyPI cloud set and its twelve runtime
version differences. Cloud urllib3 is **2.8.0**; both profiles deliberately use
SDK **1.0.13**, runtime **1.0.85**, protocol **3**. Cloud checks run in `.venv-cloud`.
The API image built remotely in ACR; Foundry resolved its uploaded hashes through
`remote_build`. No TLS bypass, vulnerable cloud downgrade or business rewrite.

| Release surface | Verified identity |
| --- | --- |
| Resource group / region | `rg-crcopilot-20260920` / `northcentralus` |
| Foundry account / project | `cog-clpttynzwwraw` / `crcopilot-20260920` |
| Model / Hosted agent | `gpt-4.1-mini`, version `2025-04-14`, Standard100 / `checkout-recovery-copilot:3` |
| PostgreSQL | `crcopilot-xfvhibddvclsw-pg`, dedicated database and explicit migrations |
| API / UI | `crcopilot-xfvhibddvclsw-api` / `crcopilot-xfvhibddvclsw-web` |
| API image digest | `a20c4a95b6e54aada08179c1124d04bcc310887ce5ff263776364a68f2da728a` |
| UI image digest | `90fd0de7c2222992cf50d5db8e5925333bc126326de4412da8cbadbed11e2a7a` |
| Deployed Hosted archive | `04bec39d337f4886517a2bf7c5195169b38bf1dbf3ccda6b1689f2c4d95a94a5`, 84 verified files |
| App Insights application ID | `0e76926e-b013-4385-b9a1-d168c5b89d34` |

API/UI build source manifest: `20d1d35eff6cb232846b6debd7c802c9702e5463c0a598a827cc5527c8f28201`.
Hosted v3 release source manifest:
`95fcd3237065e39d5cc4d9651ca555802dcc9fa1dbbe5ac3b73558b4f5c50a4d`.
Later documentation and archive-verifier corrections do not relabel those builds.
Image tags and manifests are locked. The new API identity uses account-scoped
Cognitive Services OpenAI User plus project access, not the broader inference
role originally proposed. Existing lanes and the ignored POC were not changed.

**Deployment issues and precise fixes**

- azd emitted `FOUNDRY_PROJECT_ENDPOINT`, not the lane alias expected by release
  preparation. Bound the actual validated endpoint, model and policy values in
  this environment; no endpoint was guessed and no existing environment changed.
- Hosted v1 failed with `OSError` before native execution. Moving native working
  state from the source directory into `$HOME` exposed v2's `PermissionError`.
  The downloaded deployment ZIP subsequently **confirmed missing executable
  permissions**. V3 streams only manifest-listed, hash-verified runtime bytes
  into an owned private directory under the state root, restores all four known
  executables to owner-only execution, checks executability and cleans up on
  shutdown. Runtime version/download policy did not change.
- The archive verifier now validates exact bytes, file set, hashes, versions,
  dependencies and non-symlink entries without requiring ZIP execute bits that
  Foundry strips. Execution permissions are established by the verified startup
  path instead. Actual staged runtime/protocol probes and regression tests passed.
- The health smoke helper initially omitted UI Basic authentication. It now
  reuses the command client's authentication; protected endpoints remain protected.
- Laptop DNS failed during one browser read after remediation had succeeded.
  Preserved that failure and its screenshots, re-read the **original** durable
  case, then passed the affected browser scenario on rerun.
- A local azd credential subprocess was killed before Hosted E2E's sixth Start.
  Preserved the first five results and journal; continued with the **same pending
  request UUID**, then the seventh fixture. No accepted case was replaced.
- A long Container Apps console startup command hit a WebSocket handshake 404.
  A short Python console command with the probe sent through stdin succeeded;
  no new public application endpoint or execution tool was added.

**Acceptance evidence** lives privately under `.acceptance/cloud-release/`:

| Gate | Actual result |
| --- | --- |
| Local checks | 453 backend tests and Ruff; previously verified 45 frontend tests/build |
| Smoke | Authenticated API health and real Copilot Hosted v3 inference passed |
| Command E2E | Original API 7/7 and Hosted 7/7; strict PostgreSQL business/audit/intent/native checks for all 14 |
| Browser | All eight paths passed across the original run and targeted DNS retry; nine original cases plus one supplemental case retained |
| Native Foundry evaluations | 7/7 exact start-contract scores; every output item downloaded and matched against authoritative stored projections |
| Cross-container native restore | API replica replaced; empty native working directory; same native session restored from PostgreSQL with **73 events**; business record and saved archive unchanged |
| Additional native audit | 32 accepted cases: 31 validated completed archives; one expected read-only diagnostic abort, described below |
| Tracing | **44/44 original commands across 31 original cases**, plus supplemental browser and restore traces; 8,123 span records, zero internal missing parents or duplicate spans |

Evaluation group `eval_e44b59956a9e40fb8fb5890d66b4a0f1`, run
`evalrun_ff73094970044ec09035aa42fe0ea102`; per-item results are also retained under
the Hosted agent's `.foundry/results/crcopilot-20260920/`.

The browser diagnostic-failure fixture selected optional `read_logs`, which
failed inside the real native investigation. Its expected failed business
outcome, error trace, single start/close and absence of remediation intent were
verified. It has **no completed native archive**; no synthetic archive was created,
no strict native-audit guard was relaxed, and interrupted-call restoration is not
claimed. The original failed v1/v2 cases also remain unchanged.

Trace receipts count **215 logical model response IDs and 224 logical tool call
IDs**, not duplicate request/response/handler spans. All sampling weights are one;
safe-content checks found no prohibited payloads. Foundry's `checkout-telemetry`
connection points to the verified App Insights resource with
`isSharedToAll=false`, and Hosted traces identify agent version 3. External Foundry
ingress parents and Azure Monitor's root markers are distinguished from missing
internal parents. The restore trace is `e64a439fae8357cbf9e5142cef897d5d`.

All five owned Hosted test sessions were stopped **after ingestion verification**;
the seven evaluation items shared one session. Intended API/UI and PostgreSQL
resources remain available. Public authenticated educational networking and the
existing database-admin baseline remain explicit limitations, not Private Link.
Compaction remains enabled but unexercised; cross-case preference memory is not
implemented. No commit or push was performed.
