# Technology stack

Related documents: [architecture](architecture.md) and
[project structure](projectstructure.md).

## Shared domain

| Technology | Current role |
|---|---|
| Python 3.12 | Common language baseline |
| Pydantic v2 | Immutable validated domain and evaluation contracts |
| `Decimal` and timezone-aware `datetime` | Stable money and time semantics |
| Pytest | Deterministic simulator and dependency-boundary tests |
| Hatchling | Shared package build backend |

The shared package has no FastAPI, PostgreSQL client, Azure/Foundry SDK, telemetry,
MAF, LangGraph, or workflow-runtime dependency.

## MAF application

- Microsoft Agent Framework 1.x for the explicit workflow.
- FastAPI and Uvicorn for the application-owned API.
- Psycopg 3 for PostgreSQL repositories and checkpoint/audit persistence.
- Azure Identity plus a framework-owned Foundry model client for configured real runs.
- OpenTelemetry libraries for optional framework-local tracing.
- React 19, TypeScript, Vite, Vitest, Playwright, and CopilotKit for the UI.

## LangGraph application

- LangGraph 1.x and its PostgreSQL checkpointer for graph execution and interrupts.
- LangChain OpenAI plus Azure Identity for the framework-owned Foundry adapter.
- FastAPI, Uvicorn, Psycopg 3, and Pydantic for the backend.
- Optional Azure Monitor/OpenTelemetry integration owned by the app.
- React 19, TypeScript, Vite, Vitest, Playwright, and CopilotKit for the UI.

Dependency ranges remain in each application's `pyproject.toml` and `package.json`;
this document describes roles rather than duplicating lock data.

## Local data dependency

Root `compose.yaml` starts one PostgreSQL 16 container. MAF owns the
`maf_double_charge` schema. LangGraph owns `langgraph_app` for application audit and
`langgraph_checkpoints` for native saver tables. Application scripts create and
migrate these schemas.

## Testing boundary

Backend and frontend unit tests use local fakes and in-memory adapters where
appropriate. Shared tests require neither PostgreSQL nor Foundry. Real model-backed
smoke runs require caller-provided Foundry settings and an available identity.

## Deployed Azure stack

| Component | MAF lane | LangGraph lane |
|---|---|---|
| Region | `northcentralus` | `northcentralus` |
| Model | `gpt-5.6-sol` `2026-07-09`, Global Standard | `gpt-5.6-sol` `2026-07-09`, Global Standard |
| Hosted protocol/runtime | Responses 2.0 / Python 3.13 | Responses 2.0 / Python 3.13 |
| Application hosting | React/nginx + private FastAPI Container Apps | React/nginx + private FastAPI Container Apps |
| Durable storage | PostgreSQL Flexible Server | PostgreSQL Flexible Server |
| Images | Lane-owned ACR | Lane-owned ACR |
| Telemetry | Application Insights + Log Analytics | Application Insights + Log Analytics |

Container images use release-specific tags. Hosted agent code uses Foundry direct
code deployment and remote dependency resolution rather than the application ACR.
