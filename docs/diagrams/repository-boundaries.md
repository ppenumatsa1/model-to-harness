# Repository boundaries

Canonical detail: [architecture](../design/architecture.md) and
[project structure](../design/projectstructure.md).

```mermaid
flowchart LR
    Shared[shared: domain and deterministic simulators]
    MAF[MAF application]
    LG[LangGraph application]
    DB[(one local PostgreSQL service)]
    MAF --> Shared
    LG --> Shared
    MAF -->|maf schema| DB
    LG -->|langgraph schema| DB
    MAF -. no imports .- LG
```

The root database service is a developer dependency, not shared application
infrastructure. Each application independently owns migrations and repositories.
