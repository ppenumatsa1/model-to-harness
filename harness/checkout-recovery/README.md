# Checkout recovery harness

This domain demonstrates adaptive, controlled recovery of a failed e-commerce
checkout. A harness receives the goal, chooses among bounded diagnostic tools,
uses task artifacts and a triage skill, requests approval for consequential
work, and proves the result from business-system evidence.

The first implementation is [MAF](maf/). Future harness implementations are
independent siblings, not adapters around the MAF application.

## Design contract

1. [Product requirements](docs/prd.md)
2. [Business rules](docs/business-rules.md)
3. [Human approval](docs/hitl-approval-conditions.md)
4. [User flow](docs/userflow.md)
5. [Architecture](docs/architecture.md)
6. [Technology stack](docs/techstack.md)
7. [Project structure](docs/projectstructure.md)

The separate double-charge implementations own their
[MAF design](../../agent-framework/double-charge/maf/docs/design/) and
[LangGraph design](../../agent-framework/double-charge/langgraph/docs/design/)
documentation.
