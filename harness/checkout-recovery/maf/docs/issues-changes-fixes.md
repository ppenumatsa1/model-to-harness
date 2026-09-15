# Checkout-recovery MAF implementation ledger

## Scope

This ledger records implementation decisions, defects, fixes, and observed
validation evidence for the independent MAF checkout-recovery harness. It is
not a substitute for the framework-neutral domain contract in `../../docs/`.

## Initial decisions

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
