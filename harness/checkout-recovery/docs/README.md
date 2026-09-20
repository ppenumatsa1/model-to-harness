# Checkout recovery design

These documents define the framework-neutral checkout-recovery contract. They
apply to future independent harness implementations; application-specific
delivery evidence belongs in the relevant lane.

For the actual MAF runtime, API, UI, storage and release behavior, use its
[implementation design](../maf/docs/design/prd.md) and
[4+1 architecture](../maf/docs/design/architecture.md). Its seven-document set
is independent of this domain contract.

The independent [Copilot SDK lane](../copilot-sdk/) is in development. Its
[ledger](../copilot-sdk/docs/design/issues-changes-fixes.md) separates local
acceptance from cloud deployment results.

The request is: **Investigate failed order 8472, safely resolve it, and prove
that the order is healthy.**

## Learning reference

[General-purpose vs managed harness: who owns what?](harness-responsibilities.md)
compares framework assembly with packaged-harness configuration through a checkout
flow and responsibility tables. It distinguishes current MAF behavior from the
proposed Copilot SDK lane; it does not add business requirements.
