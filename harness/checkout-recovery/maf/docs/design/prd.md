# MAF checkout-recovery product requirements

## Product and audience

This educational application investigates a simulated failed checkout and
demonstrates controlled recovery. It is for developers comparing an adaptive
agent investigation with deterministic application authority, not for processing
real payments or customer data.

The [checkout domain contract](../../../docs/README.md) describes requirements
independent of a framework. This design documents this lane's implementation.
The double-charge MAF lane is a structural reference, not a runtime dependency
or a specification of checkout's features.

## Current requirements

- Start one of seven checkout fixtures with an explicit command. A supplied
  request UUID identifies the case; equivalent retries recover the existing
  result, while a different fixture with the same identity conflicts.
- In MAF mode, let the harness select the order of bounded read-only diagnostics,
  load the checkout-triage skill and write an internal workspace plan. Permit
  at most one optional inventory-specialist delegation.
- Require order, payment and inventory tool evidence and a nonempty plan before
  accepting an investigation as complete. The deterministic simulator, not
  model prose, determines the diagnostic disposition and remedy.
- Automatically recover eligible inventory within the configured quantity bound.
  Pause captured-payment refunds for a separately recorded reviewer decision
  and a subsequent explicit Resume command.
- Persist remediation intent and recover equivalent operations by identity and
  fingerprint. Verify business records before reporting `recovered`.
- Offer safe case, audit and artifact-metadata queries through the application
  service. Restore a selected case from its URL and refresh after commands or
  when the user requests it.
- Support independently hosted FastAPI/UI and Foundry Responses transports
  through the same checkout-owned runtime construction and application service.

## Safety and quality

PostgreSQL is the deployed business authority for cases, approvals, audit,
remediation and verification. MAF session/workspace serialization is separately
stored and is not consulted to authorize a business resume.

The browser receives allowlisted state, fixed audit summaries and artifact
metadata, never prompts, raw plans, framework state, simulator snapshots,
operation fingerprints or service credentials. Production requires PostgreSQL,
MAF execution and the API token for the HTTP host. The offline `scripted`
development mode is explicit, not a fallback after a failed live investigation.

The HTTP proxy authenticates this educational UI. A reviewer ID is supplied
through that boundary; it is not an independently verified reviewer identity.
The model has no business-write or approval tools.

## Acceptance and non-goals

Acceptance includes local backend/frontend checks, real-MAF command and browser
tests, durable restart/resume, Hosted smoke, seven scenarios per transport,
independent PostgreSQL audits and all seven native exact-contract evaluation
items. Deployment identity and executed results belong in the
[dated ledger](issues-changes-fixes.md), not in undated health assertions.

This lane does **not** implement the double-charge workflow graph, native
checkpoint-based approval continuation, paginated case history, native SSE,
AG-UI, CopilotKit, or selected-run chat. Its UI is a selected-case recovery
workspace, not the double-charge three-pane experience.

Real downstream integrations, production identity/network hardening and a
general crash-recovery worker are outside this example. Trace presence is not
equivalent to complete parentage: the historical API tool-parent gap is preserved
in the ledger. Current local source retains sanitized native parent spans; cloud
ingestion and hierarchy verification await the later deployment acceptance.
