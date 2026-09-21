# MAF checkout business scenarios and rules

The seven fixtures in the [UI](../../frontend/src/App.tsx) and
[command matrix](../../evals/checkout_recovery_cases.json) exercise simulated
order, payment and inventory systems. None submits a real payment or refund.

## Scenario overview

Expected terminal results assume the indicated explicit reviewer commands.
Start-only evaluations leave the two approval scenarios paused instead.

| Fixture | What it demonstrates | Human action | Terminal result |
| --- | --- | --- | --- |
| `recoverable-inventory-reservation` | Recover an eligible reservation | None | `recovered` |
| `captured-payment-approved-remediation` | Refund a captured payment after review | Approve, then resume | `recovered` |
| `payment-pending-manual-review` | Ambiguous payment cannot be repaired automatically | None | `manual_review` |
| `diagnostic-read-failure` | Authoritative diagnostic read fails | None | `failed`, `diagnostic_read_failed` |
| `denied-approval` | Reviewer declines consequential remediation | Deny, then resume | `closed_denied` |
| `uncertain-remediation-recovery` | Recover an already-applied operation after an uncertain response | None | `recovered` |
| `verification-mismatch` | Submitted remediation does not establish expected final state | None | `manual_review`, `verification_mismatch` |

## Scenario walkthroughs

### Recover inventory reservation

Gather the required diagnostic facts and internal workspace plan. Application
policy selects reservation recovery from deterministic evidence. If quantity
is within `max_auto_inventory_quantity` (default one), persist intent, submit
the simulator operation, reload authoritative state and verify before closure.
Above the bound, route to manual review without automatic remediation.

### Captured payment requires approval

Complete investigation, persist a refund intent and bind an approval request to
the current run and simulator evidence hash. Return `waiting_approval`.
After approval and separate resume, apply the refund and verify cancellation,
refunded payment, released reservation and applied remediation together.

### Pending payment manual review

An ambiguous payment produces a deterministic `manual_review` disposition.
Close for manual review without submitting a remedy. Model recommendations
cannot turn missing or ambiguous evidence into a verified recovery.

### Diagnostic read failure

The final deterministic diagnostic read fails. Close with
`diagnostic_read_failed`; no remedy is submitted. This is distinct from
`harness_failed`, which means the bounded investigation itself did not complete.

### Denied approval

Persist the denial, reviewer and reason. Recording the decision leaves the case
paused. A separate resume applies that durable decision and closes
`closed_denied` without a remediation side effect.

### Uncertain remediation recovery

The simulator applies the operation but loses its first response. Save its
snapshot and uncertainty audit, reconstruct it from durable state, and retry
the **same** operation identity and fingerprint. Verify the recovered result.
This implemented recovery is one retry for the simulated uncertainty, not
unbounded retries or an exactly-once guarantee for an external payment service.

### Verification mismatch

The operation is recorded, but independent verification does not match all
expected states. Report `manual_review` and `verification_mismatch`, never
`recovered` merely because submission returned successfully.

## Approval and resume rules

1. `record_approval` requires a nonblank reviewer and reason, the current approval
   request UUID, a pending case and unchanged evidence. Conflicting decisions
   or stale evidence are rejected.
2. An exact recorded-decision retry with the same reviewer and reason returns
   the recorded case. It does not trigger business continuation.
3. `resume_case` reads the persisted decision. Pending approval remains paused;
   denial closes without remediation; approval continues only with valid
   evidence. Repeating resume for a closed case returns that case.

Opening a URL, refreshing, reading framework state or discussing a case cannot
approve or resume it. Checkout resume does not accept a double-charge checkpoint
ID or a separate resume-operator field. Its current command contract is
case-keyed; do not document features it does not implement.

## Core business rules

- **Authority:** the application state machine and deterministic simulator own
  diagnosis, policy, remediation and verification. Harness completion is not
  business success.
- **Isolation:** each case has its own simulator snapshot and operation intent.
  PostgreSQL transaction-scoped advisory locks serialize commands for that case.
- **Idempotency:** a supplied start UUID is bound to one fixture. Remediation
  intent binds an operation UUID and fingerprint to the proposed action.
- **Verification:** inventory recovery expects confirmed order, authorized
  payment, reserved inventory and applied remediation. Refund recovery expects
  cancelled order, refunded payment, released inventory and applied remediation.
- **Failure:** unavailable evidence, failed investigation and verification
  mismatch remain explicit outcomes. A `no_action` diagnostic closes for manual
  review in this implementation; there is no separate successful no-action
  terminal status.

See [service code](../../backend/src/checkout_recovery_maf/application/service.py),
[user flow](userflow.md) and [architecture](architecture.md).
