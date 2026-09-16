# Documentation

Start with [Part 1](articles/model-to-harness.md), then choose an implementation.
This directory contains articles and navigation, not a shared implementation
design specification.

## Implementation design

Each lane independently owns seven documents, combining scenarios, business
rules and human approval in its own `business-rules.md`. Each set
describes its lane's actual code, configuration, UI, and evidence rather than assuming
feature parity with the other framework.

| Topic | Microsoft Agent Framework | LangGraph |
| --- | --- | --- |
| Product requirements | [MAF](../agent-framework/double-charge/maf/docs/design/prd.md) | [LangGraph](../agent-framework/double-charge/langgraph/docs/design/prd.md) |
| Business rules | [MAF](../agent-framework/double-charge/maf/docs/design/business-rules.md) | [LangGraph](../agent-framework/double-charge/langgraph/docs/design/business-rules.md) |
| Human approval | [MAF](../agent-framework/double-charge/maf/docs/design/business-rules.md#approval-and-resume-rules) | [LangGraph](../agent-framework/double-charge/langgraph/docs/design/business-rules.md#approval-and-resume-rules) |
| User flow | [MAF](../agent-framework/double-charge/maf/docs/design/userflow.md) | [LangGraph](../agent-framework/double-charge/langgraph/docs/design/userflow.md) |
| 4+1 architecture | [MAF](../agent-framework/double-charge/maf/docs/design/architecture.md) | [LangGraph](../agent-framework/double-charge/langgraph/docs/design/architecture.md) |
| Technology stack | [MAF](../agent-framework/double-charge/maf/docs/design/techstack.md) | [LangGraph](../agent-framework/double-charge/langgraph/docs/design/techstack.md) |
| Project structure | [MAF](../agent-framework/double-charge/maf/docs/design/projectstructure.md) | [LangGraph](../agent-framework/double-charge/langgraph/docs/design/projectstructure.md) |
| Issues, changes, and fixes | [MAF](../agent-framework/double-charge/maf/docs/design/issues-changes-fixes.md) | [LangGraph](../agent-framework/double-charge/langgraph/docs/design/issues-changes-fixes.md) |

Workflow and boundary diagrams live within each lane's architecture and user-flow
documents. Historical release evidence belongs in the corresponding lane ledger.

## Articles

- [Part 1: From Models to Harnesses](articles/model-to-harness.md)
- [Part 2: Agent Frameworks](articles/02-agent-frameworks.md)
- [Part 3: Agent Harnesses](articles/03-agent-harnesses.md)
- [Part 4: Runtime Infrastructure](articles/04-runtime-infra.md)
- [LinkedIn articles and assets](linkedin/)

The separate [checkout-recovery harness documentation](../harness/checkout-recovery/README.md)
remains with that project.
