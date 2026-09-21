# Business rules and human approval

The [neutral business rules](../../../docs/business-rules.md) and
[approval contract](../../../docs/hitl-approval-conditions.md) apply unchanged.

| Boundary | Enforced by |
| --- | --- |
| Read only the selected checkout | Case-scoped diagnostic tools |
| Select allowed automatic inventory recovery | Application policy and quantity bound |
| Require approval for captured-payment refund | Application creates durable pending request |
| Bind decision to current case/request/evidence | Application validates reviewer, reason, decision and request identity |
| Approval does not execute remediation | Separate explicit Resume command |
| Pending, denied or stale approval cannot authorize a write | Application checks persisted state |
| Retry must not duplicate a side effect | Durable remediation intent and simulator idempotency |
| Recovery must be proven | Business evidence verification, not model completion text |

PostgreSQL is authoritative. Native Copilot state is private framework context;
tool permission callbacks and remembered conversation statements are not reviewer
decisions. The investigator has no refund or approval tools.

All business side effects are deterministic simulations. A harness timeout,
permission denial or incomplete investigation must fail explicitly, never switch
silently to scripted success.
