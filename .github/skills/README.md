# Vendored third-party skills

This repository keeps a deliberately small set of upstream skills to help contributors
use current framework and platform guidance without embedding that guidance in the
application runtime.

Included skills:

- `langgraph-docs`
- `azure-ai-projects-py`
- `azure-identity-py`
- `azure-monitor-opentelemetry-py`
- `fastapi-router-py`
- `pydantic-models-py`
- `microsoft-foundry`

The Microsoft skills originate from the
[`microsoft/skills`](https://github.com/microsoft/skills) catalog and are vendored in
the reference repositories at pinned upstream revisions. `langgraph-docs` is an MIT
licensed LangChain documentation-navigation skill from the LangGraph reference
repository.

The imported snapshot was copied from:

- `ppenumatsa1/maf-monorepo`, `agents/order-resolution/foundry-public/.github/skills`
- `ppenumatsa1/langgraph-wf-monorepo`,
  `agents/order-resolution/foundry-public/.github/skills`

Snapshot date: 2026-09-01.

Repository-owned skills from those projects were intentionally excluded. In
particular, this repository does not vendor their deployment, release, design-review,
boundary-review, PostgreSQL, AG-UI, MAF-specific, LangGraph-specific, or evaluation
skills.

Skills are contributor guidance only. They are not imported by either application,
packaged into runtime containers, or treated as a shared framework abstraction.

