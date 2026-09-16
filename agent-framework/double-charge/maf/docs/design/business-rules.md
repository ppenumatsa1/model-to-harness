# MAF business scenarios and rules

Start here for the six scenarios in the MAF demo picker, their business outcomes,
and the approval rules. Refunds and notifications are simulated, not real payment
or delivery operations. See [user flow](userflow.md) for the UI journey and
[architecture](architecture.md) for implementation details.

## Scenario overview

These are the choices returned by `GET /api/scenarios`. Expected outcomes assume
the indicated human decision and a separate Resume command where required.

| Scenario fixture | What it demonstrates | Human action | Expected business outcome |
| --- | --- | --- | --- |
| `duplicate-confirmed` | Normal duplicate-charge resolution | Approve, then resume | `completed_refunded` |
| `no-duplicate` | Distinct purchases, not a duplicate | None | `completed_no_refund` |
| `approval-denied` | Reviewer declines an eligible refund | Deny, then resume | `closed_denied` |
| `transient-failure` | Billing reads exhaust bounded retries | None | `failed`, before refund submission |
| `retry-safe-refund` | Recover a refund after an uncertain response | Approve, then resume | `completed_refunded` |
| `resumed-approval` | Continue after a durable approval pause | Approve later, then resume | `completed_refunded` |

`verification-mismatch` is not a normal MAF demo choice. It remains available to
internal regression/evaluation harnesses to prove that failed verification never
claims success. Existing cases remain readable in history; their evidence is
not deleted.

## Scenario walkthroughs

### Duplicate confirmed

Investigate the complaint and identify matching charges. Run billing and policy
checks in parallel, then request human approval. After approval and explicit
resume, submit the refund, verify it, simulate the customer notification and
close the case as refunded.

### No duplicate

Read the billing evidence successfully and find that the charges are distinct
purchases. Close without approval, refund or notification. An unavailable billing
system is not evidence that there was no duplicate.

### Approval denied

Confirm the duplicate and pass both checks, but record the reviewer's denial and
reason. The case stays paused until Resume applies that decision, then closes
without a refund or notification.

### Transient failure

Billing reads keep failing until the attempt limit is reached. Stop with an
explicit failure before approval or refund submission. This is an unsuccessful
automated run, not a successfully resolved customer complaint.

### Retry-safe refund

After approval and resume, the simulator stores a refund but its first response
is uncertain. Retry with the same operation identity, recover the existing refund
and verify it instead of issuing another one. Only then simulate notification
and close as refunded.

### Resumed approval

Complete the checks and leave the case paused for a later decision. Reopening
the case restores its persisted state; it does not approve or resume it.
Record approval when ready, then explicitly resume from the saved checkpoint.
The remaining refund, verification and closure steps match approved success.

## Approval and resume rules

Only a confirmed duplicate that passes both checks reaches human approval.

1. The reviewer records approval or denial, with their identity and reason.
2. The case stays paused until an operator enters their identity and selects **Resume**.
3. Approval continues to refund and verification; denial closes without refund.

Reopening a case or discussing it in chat does not authorize an action.
Once the run has ended, the earlier approval is history, not an active control.

## Core business rules

- **Duplicate evidence:** two distinct captured charges must match the account, purchase reference, amount and currency.
- **Refund eligibility:** the charges must have a positive value and fall within the 120-day policy window. Billing and policy must both pass.
- **Reliable decisions:** missing or failed billing evidence is not proof of no duplicate. An explicitly ineligible case closes without refund.
- **Safe retries:** attempts are limited. A refund retry reuses the original operation identity rather than creating another refund.
- **Verified closure:** confirm exactly one matching refund before closing as refunded and simulating the customer notification.
- **Uncertain outcomes:** stop and flag the case for investigation rather than claiming success.
