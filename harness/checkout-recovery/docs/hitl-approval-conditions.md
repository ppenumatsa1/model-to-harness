# Human approval conditions

Approval is a durable command boundary, never a blocking model wait.

| Condition | Required behavior |
| --- | --- |
| Read-only diagnosis | No approval; tools remain scoped to the case. |
| Recreate an allowed inventory reservation | Deterministic policy allows automatic recovery only when the reservation quantity is at or below the configured `max_auto_inventory_quantity` bound; otherwise route to manual review. |
| Refund, payment change, order override, or customer-impacting cancellation | Persist a pending request and require reviewer approval. |
| Approval command retry | Accept only the same decision, reviewer, reason, case, run, and request identity. |
| Resume | Load the persisted decision; reject arbitrary chat or resume payload as authority. |
| Missing, denied, or stale approval | Do not remediate; close denied or route to review as appropriate. |
