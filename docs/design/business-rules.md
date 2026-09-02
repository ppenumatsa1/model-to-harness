# Double-charge business rules

These rules are defined before framework code so the MAF and LangGraph versions can
be evaluated against the same behavior.

Related documents: [product requirements](prd.md),
[approval conditions](hitl-approval-conditions.md), and
[architecture](architecture.md).

## Authoritative records

- A charge is identified by `charge_id` and belongs to one account.
- Money uses decimal amounts plus a three-letter currency code.
- Only captured charges are eligible for duplicate matching or refund.
- Billing records and refund records are authoritative. Model output is not.

## Duplicate detection

A duplicate is confirmed only when two distinct captured charges on the same account
have the same purchase reference, amount, and currency. Candidates are sorted by
charge timestamp and charge ID; the first matching pair is selected, making the
result deterministic.

No matching pair routes directly to `completed_no_refund`. A failed authoritative
read is not treated as “no duplicate”: reads receive the configured bounded retry,
then route to `failed` with `transient_billing_read`.

## Billing and policy validation

After a duplicate is confirmed, billing validation and policy evaluation may run in
parallel. The workflow joins both results before routing.

Billing validation requires:

- both evidence IDs still exist on the account;
- both charges remain captured;
- account, purchase reference, amount, and currency still match.

The local policy simulator requires positive value, captured charges, and a charge
age no greater than 120 days at its fixed evaluation time. Failed billing validation
routes to failure. Ineligible policy routes to a closed, no-refund outcome. Ambiguous
evidence routes to manual review.

## Approval

Every eligible duplicate refund in this teaching scenario requires approval. The
workflow persists a checkpoint before exposing a pending approval. Approval is a
separate command containing checkpoint ID, decision, reviewer ID, and optional
reason. It is never inferred from chat text.

- Approval resumes from persisted state.
- Denial closes the case without a refund.
- A decision must target the current pending checkpoint.
- Repeating the same recorded decision is safe; conflicting decisions are rejected.

## Refund idempotency and verification

The refund boundary requires a non-empty idempotency key. The billing simulator
atomically indexes refunds by that key:

- the first submission stores one deterministic refund;
- a repeated equivalent submission returns the stored refund;
- reuse for a different account, charge, amount, or currency is an error;
- an uncertain response may occur after storage, so retry uses the same key.

Each framework also persists an application-owned refund ledger in PostgreSQL. That
ledger records the request fingerprint and simulator refund ID so retry and recovery
can reconstruct the same business result after a process restart. Reusing a key for a
different fingerprint is a conflict.

Retries are at-least-once attempts, not an exactly-once claim. Success is declared
only after verification finds exactly one refund matching the idempotency key and
business data. Zero or multiple matches route to manual review.

## Notification and terminal states

Notification occurs only after a verified refund. No-duplicate, policy-ineligible,
approval-denied, failed, and manual-review routes do not claim that a refund was
completed.

Terminal statuses are:

- `completed_no_refund`
- `completed_refunded`
- `closed_denied`
- `manual_review`
- `failed`

Nonterminal statuses are `running` and `waiting_approval`.

## State, memory, context, and audit

- **Workflow state** is the current execution truth and next transition.
- **Checkpoint** is the durable resume boundary.
- **Audit history** is the ordered, append-only record of decisions and actions.
- **Selected memory** is a small set of intentionally retained customer or case facts.
- **Model context** is a temporary projection and is never authoritative.

Audit events use monotonically increasing sequence numbers within a run. They record
safe summaries and correlation IDs, not hidden reasoning, credentials, raw prompts,
database internals, or unrestricted tool payloads.

## Current fixture coverage

The shared package supplies fixtures for duplicate confirmed, no duplicate, approval
denied, exhausted transient reads, uncertain refund response with safe retry, resumed
approval, and refund verification mismatch. Both applications map their native state
to the same normalized expected outcomes.
