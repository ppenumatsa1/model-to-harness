# Human-in-the-loop approval conditions

The approval boundary protects the refund side effect. It is an explicit durable
command flow, not a conversational interpretation.

Related documents: [business rules](business-rules.md),
[user flow](userflow.md), and [architecture](architecture.md).

## When approval is required

Approval is requested only after all of the following are true:

1. Two distinct captured charges satisfy the duplicate rule.
2. Billing validation confirms the evidence still matches authoritative records.
3. Refund policy returns `eligible`.
4. The workflow has persisted its current state and checkpoint.
5. No terminal outcome or earlier conflicting decision exists.

No-duplicate, exhausted-read, invalid-evidence, ineligible-policy, and manual-review
routes do not open an approval request.

## Approval request contents

The durable request identifies the case/run, checkpoint, amount, currency, current
status, and safe evidence summary. It excludes model reasoning, raw prompts,
credentials, unrestricted tool results, and checkpoint payloads.

The approval command contains:

- the current checkpoint ID;
- `approve` or `deny`;
- a non-empty reviewer identifier;
- an optional concise reason.

## Command rules

- A decision must target the active pending checkpoint.
- Recording approval does not itself resume execution.
- Repeating the identical recorded decision is safe.
- A different decision or reviewer for a resolved checkpoint is a conflict.
- Denial closes the case without refund or notification.
- Approval permits a separate resume command; it does not bypass refund validation.

The current APIs preserve these semantics with framework-local routes: the MAF app
addresses approval and resume by run ID, while the LangGraph app addresses them by
case ID.

## Resume preconditions

Resume is allowed only when the persisted case is waiting for approval, the supplied
checkpoint is current, and a durable decision exists. On approval, execution
continues with the original idempotency key. On denial, the workflow follows the
closed-denied route without calling billing.

## Audit evidence

The durable history should show checkpoint creation, approval requested, decision
recorded, resume attempted, resume accepted or rejected, and the selected transition.
UI or AG-UI events are projections of this evidence, not its source.
