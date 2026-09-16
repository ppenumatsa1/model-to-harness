# LangGraph double-charge product requirements

This lane is an independently packaged educational application: one support case
demonstrates native graph execution, deterministic controls, durable approval and
verified simulated refunds. Its implementation is not the specification for any
other framework.

Related: [business rules](business-rules.md), [architecture](architecture.md),
[user flow](userflow.md), [implementation ledger](issues-changes-fixes.md).

## Audience and goals

Developers and architects can inspect conditional routes, concurrent validations,
reducers, retry boundaries, native checkpoints, interrupts and recovery. Reviewers
can distinguish durable business evidence from model text and browser projections.
The model normalizes a complaint and drafts a notification; it never decides
whether a duplicate exists, approves a refund or certifies a payment.

## Current capabilities

| Capability | Implemented boundary |
| --- | --- |
| Start investigation | Explicit `POST /api/cases` with operator identity, complaint, customer and deterministic scenario. |
| Branch and join | Billing and policy execute concurrently and merge checkpointed evidence. |
| Durable human decision | A native interrupt pauses execution; reviewer identity and reason record a decision; a separate operator/checkpoint command resumes. |
| Safe refund | Stable request fingerprint and idempotency key, durable receipt, independent verification. |
| History | Persisted cases, ten at a time, with cursor pagination and selected-case restoration. |
| Observation | Native committed-event SSE, independent workspace snapshots, additive AG-UI and a read-only case-scoped CopilotKit explanation. |
| Inspection | Three-pane workspace with context, timeline, state/memory/outcome, graph and business audit. |
| Business actors | New audit records distinguish caller-supplied human identities from automated system actions; missing legacy facts remain unknown. |
| Alternate transport | Hosted Responses adapter delegates explicit commands to the same lane-owned service and closes runtime resources per command. |
| Testability | Injected model/gateway/audit/saver doubles; optional isolated PostgreSQL reconstruction checks. |

The UI can observe a newly committed case while Start is still pending. Selecting
history is read-only; a new case, reviewer decision and resume are distinct user
actions. Approval and denial no longer automatically issue Resume. The caller's
identity is recorded, not authenticated or granted production authorization.

## Functional and safety requirements

An eligible duplicate must pause without a refund or terminal outcome. A decision
must bind to the current native interrupt and cannot be changed after recording.
An identical decision retry is accepted; conflicting checkpoint, decision,
reviewer or reason is rejected. Denial must not submit a refund. Success requires
exactly one matching refund identifier before notification. Uncertainty is not a
failed-payment assumption.

PostgreSQL remains authoritative for runs, audit, decisions, selected memory and
refund receipts. Native checkpoints are framework-owned in a separate schema.
Neither replay nor retries guarantee exactly-once side effects. The browser sees
allowlisted summaries, never prompts, credentials, raw checkpoint bodies, hidden
reasoning or unrestricted tool input/output.

Configuration must be lane-local and independent of launch directory in a source
checkout. Process environment overrides dotenv; constructors and `_env_file`
remain explicit test/application controls. Missing real storage/model configuration
fails before external setup. Local tests cannot silently inherit a private `.env`
or install an Azure exporter.

## Acceptance and non-goals

Six demo choices cover verified refund, no duplicate, denial, exhausted reads,
retry-safe uncertainty and resumed approval. The seventh fixture, verification
mismatch, remains in regression/evaluation coverage and historical cases.
Targeted regressions also cover policy ineligibility, missing refund
identifiers, checkpoint reconstruction, conflicting commands, pagination,
event replay/commit ordering, immutable audit facts, legacy reads and privacy.
See the [ledger](issues-changes-fixes.md) for dated evidence, not live-health claims.

Real payment processing, provider reconciliation, production reviewer
authentication/authorization, automatic crash recovery, a shared application
platform, multi-agent delegation and production network/security certification
are out of scope. This source/configuration update does not deploy the application
or attest the health of any historical hosted version.
