# MAF double-charge product requirements

## Product and audience

This independently owned MAF teaching application turns a simulated double-charge
complaint into a durable, inspectable outcome. Developers learn native workflow
composition; architects inspect durability boundaries; support users and reviewers
can follow a case without treating model prose as business authority.

The implementation is described by this lane's [architecture](architecture.md),
[business rules](business-rules.md), [approval rules](business-rules.md#approval-and-resume-rules),
and [user journey](userflow.md). The shared domain supplies deterministic fixtures,
not a shared application specification or runtime.

## Current requirements

| Capability | MAF requirement and acceptance |
| --- | --- |
| Case intake | Explicit Start accepts a complaint, customer, scenario and nonblank operator. Client-supplied case identity enables observation before the synchronous command returns. |
| Investigation | Model normalization is bounded by deterministic account/duplicate evidence; failed reads never mean no duplicate. |
| Native orchestration | Named executors and conditional edges, parallel billing/policy validation, native fan-in and checkpoint-based approval resume. |
| Human control | Every eligible refund pauses. Record approve/deny with reviewer and reason, then require a separate Resume operator and current checkpoint. Chat cannot decide or resume. |
| Side effects | Preserve one request identity across retries/reconstruction, reject conflicting fingerprints, verify one durable simulated refund before notification. |
| Workspace | Three panes: persisted case history; execution/context/commands/inspectors; deterministic business audit. History loads ten cases per page and deep links restore old cases. |
| Observation | Native SSE replays committed events by cursor and follows safe snapshot changes; selected-run AG-UI/CopilotKit is additive and read-only. |
| Audit | Version-2 business milestones retain recorded time, actor, decision/reason and bounded evidence. System work is not attributed to the human opener. |
| Isolation | The API, UI, runtime, persistence, telemetry, packaging, tests and operational docs stay in MAF. Explicit fake adapters support offline validation. |
| Configuration | Editable entrypoints read only `maf/.env`, independent of launch directory. Process environment wins; installed/hosted packages remain environment-driven. |

## Safety and quality

PostgreSQL is authoritative for runs, approvals, selected memory, outcomes and
audit records. Checkpoints are owned by MAF and stored through its lane adapter.
An event is historical evidence; the header is a current-state snapshot. Neither
an SSE frame nor a model explanation replaces either store.

Browser projections must exclude prompts, hidden reasoning, credentials,
connection strings, checkpoint bodies, raw idempotency keys and unrestricted
state/tool payloads. Operator/reviewer values are caller-supplied identifiers,
**not authenticated identities**. Reviewer reasons and actor metadata stay out
of model facts and general telemetry.

Approval alone must not execute a refund. A lost command response must not cause
an automatic repeat. Native retries are not an exactly-once or lifetime-attempt
guarantee. No success notification is allowed for denial, invalid evidence,
uncertain refund exhaustion or verification mismatch.

## Acceptance and non-goals

The seven deterministic scenarios cover verified refund, no duplicate, denial,
bounded read failure, retry-safe refund, resumed approval and verification
mismatch. Focused regressions additionally cover policy ineligibility, uncertain
exhaustion, pagination/live-update races, safe projections and actor restoration.
See the [ledger](issues-changes-fixes.md) for dated results rather than assuming
that tests included here have been rerun against a live deployment.

Real payments, actual notification delivery, automatic provider reconciliation,
production reviewer authorization, automatic crash recovery, production network
certification and a shared cross-framework platform are not implemented. This
change does not deploy the new workspace or actor contract, migrate data, or
establish remote health. Historical hosted v8 evidence predates the current local
workspace/audit changes.
