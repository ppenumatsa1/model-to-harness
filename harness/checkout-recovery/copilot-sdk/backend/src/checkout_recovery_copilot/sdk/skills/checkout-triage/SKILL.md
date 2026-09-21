---
name: checkout-triage
description: Diagnose one synthetic failed checkout using read-only evidence and a bounded plan.
---

# Checkout triage

Read order, payment, and inventory evidence before recommending a remedy.
`read_logs` is optional. `delegate_inventory` may run the inventory specialist
once; its completed read supplies inventory evidence.

Write a short diagnostic plan to `plan.md` through `write_plan`, then read it
through `read_plan`. These tools access only this case's bounded workspace.
Do not run shell commands, browse, inspect other files, or request customer data.
Never approve, refund, remediate, or claim recovery. Application policy and
verification, not the model, decide the business outcome.
