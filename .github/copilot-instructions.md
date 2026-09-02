# Copilot instructions

This is a public educational repository comparing independent Microsoft Agent
Framework and LangGraph implementations of the same double-charge workflow.

## Boundaries

- Keep `agent-framework/double-charge/maf` and
  `agent-framework/double-charge/langgraph` fully independent.
- Do not create shared API, UI, orchestration, persistence, telemetry, deployment, or
  CI abstractions.
- Keep `shared/` limited to framework-neutral domain models, deterministic
  simulators, fixtures, and evaluation contracts.
- PostgreSQL is authoritative for workflow state and auditing. Framework checkpoints
  remain framework-owned.
- Human approval is a durable pause/resume command boundary, never a blocking wait or
  a decision inferred from chat.
- Side effects require idempotency plus verification; framework retries are not an
  exactly-once guarantee.

## UI and event safety

- Native durable events are the source of truth.
- AG-UI and CopilotKit are additive selected-run projections.
- Start, approve, and resume through explicit FastAPI commands.
- Show safe decision summaries, not hidden chain-of-thought.
- Never expose prompts, credentials, connection strings, raw checkpoint payloads, or
  unrestricted tool arguments/results to the browser.

## Skills

Use only the relevant vendored third-party skill:

- `langgraph-docs` for current LangGraph documentation.
- `azure-ai-projects-py` for Foundry project SDK work.
- `azure-identity-py` for Entra and managed identity.
- `azure-monitor-opentelemetry-py` for Azure Monitor telemetry.
- `fastapi-router-py` for FastAPI route work.
- `pydantic-models-py` for Pydantic v2 contracts.
- `microsoft-foundry` for future hosted-agent lifecycle work.

Do not add repository-specific custom skills until the project has repeated local
patterns worth formalizing.
