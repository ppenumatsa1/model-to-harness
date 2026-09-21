# Checkout recovery harness

This domain demonstrates adaptive, controlled recovery of a failed e-commerce
checkout. A harness receives the goal, chooses among bounded diagnostic tools,
uses task artifacts and a triage skill, requests approval for consequential
work, and proves the result from business-system evidence.

The implementations are independent siblings, not adapters around one another:
[MAF](maf/) and [Copilot SDK](copilot-sdk/) (in development; see its
[acceptance ledger](copilot-sdk/docs/design/issues-changes-fixes.md)).

## Design contract

These parent documents define framework-neutral requirements and boundaries.
They are not an inventory of implemented features. The
[MAF implementation design](maf/docs/design/prd.md) provides its own seven-document
set, including [architecture](maf/docs/design/architecture.md),
[source map](maf/docs/design/projectstructure.md) and
[release ledger](maf/docs/design/issues-changes-fixes.md).

1. [Product requirements](docs/prd.md)
2. [Business rules](docs/business-rules.md)
3. [Human approval](docs/hitl-approval-conditions.md)
4. [User flow](docs/userflow.md)
5. [Architecture](docs/architecture.md)
6. [Technology stack](docs/techstack.md)
7. [Project structure](docs/projectstructure.md)

For the conceptual comparison, see
[General-purpose vs managed harness: who owns what?](docs/harness-responsibilities.md):
checkout flow, primitive ownership, and current versus proposed behavior.

The separate double-charge implementations own their
[MAF design](../../agent-framework/double-charge/maf/docs/design/) and
[LangGraph design](../../agent-framework/double-charge/langgraph/docs/design/)
documentation.
