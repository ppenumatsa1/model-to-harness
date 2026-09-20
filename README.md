# Model to Harness

**From models that answer to agent systems that finish the job.**

Model to Harness is a seven-part learning series with practical reference
implementations. Its goal is to explain what it takes to turn model reasoning
into reliable work: coordinating actions, preserving progress, respecting human
authority, recovering from failures, and verifying outcomes.

The articles introduce the concepts; the code makes the design choices concrete.
Two business scenarios ground the series: **resolving a duplicate card charge**
and **recovering a failed checkout**. Independent implementations let you compare
framework and harness approaches against the same business requirements.

## The seven-part series

Start with the [series overview](docs/articles/model-to-harness.md). The parts
explore complementary capabilities and cross-cutting concerns, not a mandatory
maturity ladder.

| Part | Topic | What it covers | LinkedIn article | Code references |
| --- | --- | --- | --- | --- |
| 1 | **From models to harnesses** | The mental model: what models, agents, frameworks, harnesses, and runtimes each contribute. | [Part 1](docs/linkedin/01-model-to-harness.md) | N/A - conceptual overview |
| 2 | **Agent frameworks and orchestration** | Explicit workflows, state, human approval, retries, and verified completion of a double-charge case. | [Part 2](docs/linkedin/02-agent-frameworks.md) | [Microsoft Agent Framework](agent-framework/double-charge/maf/) · [LangGraph](agent-framework/double-charge/langgraph/) |
| 3 | **Agent harnesses** | Context, skills, tools, permissions, workspaces, and bounded investigation for checkout recovery. | [Part 3](docs/linkedin/03-agent-harnesses.md) | [MAF harness](harness/checkout-recovery/maf/) · [Copilot SDK harness](harness/checkout-recovery/copilot-sdk/) |
| 4 | **Runtimes and hosted agents** | Where work runs: sessions, persistence, isolation, recovery, scaling, and hosting choices. | Planned | [MAF infrastructure](harness/checkout-recovery/maf/infra/) · [Copilot SDK infrastructure](harness/checkout-recovery/copilot-sdk/infra/) |
| 5 | **Memory and knowledge** | Separating state, memory, and context; retrieval, provenance, retention, and safe updates. | Planned | Planned |
| 6 | **Observability and evaluations** | Tracing execution, evaluating outcomes, defining release gates, and monitoring deployed systems. | Planned | [MAF evals](harness/checkout-recovery/maf/evals/) · [MAF telemetry](harness/checkout-recovery/maf/observability/) · [Copilot SDK evals](harness/checkout-recovery/copilot-sdk/evals/) · [Copilot SDK telemetry](harness/checkout-recovery/copilot-sdk/observability/) |
| 7 | **Identity, security, and governance** | Authority, scoped access, approvals, auditability, and control of consequential actions. | Planned | Planned |

Article links point to the Markdown versions in [`docs/linkedin/`](docs/linkedin/).
Planned entries will be linked as they are added. Code references point to
existing examples; they do not imply that the corresponding article is complete.

## Explore the implementations

Follow each linked implementation's README for setup, configuration, and running
the example. Its design documents explain the architecture and business rules;
its release ledger records dated deployment and verification results.

The applications are deliberately independent, with their own APIs, UIs,
persistence, tests, and deployment assets. Only framework-neutral domain models,
fixtures, and deterministic simulators belong in [`shared/`](shared/).
See the [documentation index](docs/README.md) for further reading.

## License

Licensed under the [MIT License](LICENSE). Third-party dependencies and vendored
materials remain subject to their respective licenses.

## Disclaimer

This is an independent educational project, not a production payment or
customer-support system. Payments, notifications, and downstream business
operations are simulated. Examples are provided **as is**, without warranty;
demo defaults and deployments must not be used with real customer data or
payment credentials.

Review security, privacy, reliability, and operating costs before adapting these
examples for real workloads. Azure deployments and model usage can incur charges.
References to products and platforms do not imply vendor endorsement.
