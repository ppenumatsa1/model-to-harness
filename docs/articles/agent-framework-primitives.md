# Part 2 outline: Agent framework primitives in one durable case

Part 1 established the progression from model to agent, framework, harness, and
runtime. Part 2 will make the framework layer concrete by implementing the same
double-charge workflow independently in Microsoft Agent Framework and LangGraph.

Implementation companions: [product requirements](../design/prd.md),
[architecture](../design/architecture.md),
[business rules](../design/business-rules.md), and
[approval conditions](../design/hitl-approval-conditions.md).

## Reader promise

The article will explain each primitive before showing framework syntax:

1. **State and transitions** — what is authoritative and how a case advances.
2. **Nodes and edges** — deterministic steps, model-backed steps, and explicit routes.
3. **Fan-out/fan-in** — parallel billing and policy checks with a deliberate join.
4. **Retries and failure routes** — bounded operational retries without disguising
   business failures.
5. **Interrupts and checkpoints** — persist, pause, approve later, and resume.
6. **Idempotency and verification** — retry a refund safely and prove one result.
7. **Events, replay, and re-execution** — inspect history without confusing reading
   old events with running work again.
8. **State, memory, and model context** — separate current truth, retained facts, and
   temporary prompts.
9. **Multi-agent patterns** — identify extension seams without turning a simple case
   into an unnecessary agent team.
10. **Managed hosting** — map local durability and identity boundaries to future
    hosted-agent operation.

## Comparison method

Both implementations will consume the shared fixtures, produce the same normalized
outcome contract, and expose equivalent commands and event vocabulary. They will not
share orchestration, API, UI, persistence, telemetry, or deployment code.

The article will close by comparing the primitives demonstrated, the framework-native
trade-offs, and the evidence required to call the case finished.
