# Checkout recovery with Copilot SDK

Investigate a failed synthetic checkout, select permitted recovery, obtain durable
human approval when required, and verify the resulting business state.

This lane implements the same [domain contract](../../../docs/prd.md) as MAF,
but owns its application and delivery code independently. Copilot supplies the
model/tool loop and native session/context features; the application supplies
checkout tools, policy, state and explicit commands.

## Required behavior

| Scenario | Expected business route |
| --- | --- |
| Recoverable inventory reservation | Automatically recreate within the configured quantity bound; verify |
| Captured payment | Persist approval request; explicitly approve and resume; verify refund |
| Payment pending | Manual review; no unsupported remediation |
| Diagnostic read failure | Explicit failure; no business side effect |
| Denied approval | Close denied; no remediation |
| Uncertain remediation response | Reconcile durable intent and evidence; do not duplicate the action |
| Verification mismatch | Do not claim recovery; preserve failure/review evidence |

Start request identities survive ambiguous responses. Browser refresh reads the
case rather than replaying commands. Native conversation restoration cannot
substitute for an authorized business Resume.

No real payment system, chat-based approval, shared cross-lane application layer,
or cross-user preference memory is included.

See the [ledger](issues-changes-fixes.md) for actual acceptance status; requirements
are not deployment evidence.
