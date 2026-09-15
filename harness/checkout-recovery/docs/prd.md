# Product requirements

## Goal

Demonstrate a harness carrying a checkout-recovery task from investigation to
a verified outcome. The agent may choose the next permitted diagnostic action;
application code owns authority, side effects, and completion.

## Functional requirements

- Start a case from an explicit command and display safe progress.
- Let the agent choose only registered read-only diagnostics for order, payment,
  inventory, and diagnostic records.
- Supply a checkout-triage skill and a case-scoped workspace artifact area.
- Permit one bounded, read-only delegated diagnostic task.
- Require a separately recorded approval and explicit resume before
  customer-impacting remediation.
- Submit remediation with stable operation identity and request fingerprint.
- Verify final order, payment, inventory, and remediation state independently.
- Return verified recovery, no-action closure, denial, manual review, or failure.

## Non-goals

- Real customer data, payment processing, browser automation, unrestricted shell
  access, or model-authorized side effects.
- Treating an agent completion signal, session checkpoint, or UI event as
  business proof.
