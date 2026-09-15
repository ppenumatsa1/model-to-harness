# Architecture

```mermaid
flowchart LR
    user[Support user or reviewer] --> api[MAF-owned FastAPI API]
    api --> harness[MAF Harness Agent]
    harness --> tools[Scoped diagnostic and remediation tools]
    harness --> workspace[Case-scoped workspace]
    tools --> store[(PostgreSQL business authority)]
    store --> audit[Audit, approval, outcome, evidence]
    audit --> projection[Safe UI/event projection]
    projection --> user
```

MAF owns the agent harness and its framework session/checkpoint behavior.
PostgreSQL owns checkout business state and auditing. A Foundry Hosted Agent
hosts the same application command service; it does not become a second source
of workflow or business authority.
