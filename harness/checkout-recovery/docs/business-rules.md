# Business rules

1. Authoritative order, payment, inventory, approval, and remediation records
   are durable application state.
2. Diagnostic tools are read-only and return typed, allowlisted facts.
3. A triage skill is procedure guidance; it grants neither tool authority nor
   business permission.
4. Customer-impacting remediation requires a persisted reviewer decision bound
   to the current case, run, proposed action, and evidence summary.
5. Equivalent retries of one remediation operation return the same durable
   result. Reusing an operation identity for different intent is a conflict.
6. A verified recovery requires matching expected order, payment, inventory,
   and remediation records. Missing or contradictory evidence routes to manual
   review or explicit failure.
7. The model can propose and prioritize work. It cannot approve a remedy or
   declare the order healthy.
