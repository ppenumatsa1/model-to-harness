# Checkout recovery design

These documents define the framework-neutral checkout-recovery contract. They
apply to future independent harness implementations; application-specific
delivery evidence belongs in the relevant lane.

For the actual MAF runtime, API, UI, storage and release behavior, use its
[implementation design](../maf/docs/design/prd.md) and
[4+1 architecture](../maf/docs/design/architecture.md). Its seven-document set
is independent of this domain contract.

The request is: **Investigate failed order 8472, safely resolve it, and prove
that the order is healthy.**
