# MAF checkout technology stack

## Backend and contracts

| Technology | Role and authority |
| --- | --- |
| Python | Installable checkout backend; manifest permits Python >=3.12, documented local acceptance uses 3.13. |
| Microsoft Agent Framework | Bounded read-only harness, model-selected diagnostics, triage skill, optional inventory delegate and internal workspace. Not the business state machine. |
| Foundry project/chat clients and Azure Identity | Server-side model access using the configured project and deployment. |
| FastAPI and Uvicorn | Explicit synchronous HTTP commands, safe queries, health checks and lifespan. |
| Pydantic v2 / pydantic-settings | Typed commands, application records, frozen safe projections and process-based configuration. |
| Psycopg 3 and connection pool | Synchronous PostgreSQL reads, transactions and per-case advisory locks. |
| Neutral `model_to_harness_shared` | Checkout records, deterministic simulator, fixtures and expected outcomes only. |

[pyproject.toml](../../pyproject.toml) defines package constraints;
[uv.lock](../../uv.lock) records resolved dependencies. Do not infer installed
versions from this overview or upgrade dependencies to match another lane.

## Frontend

React, TypeScript and Vite implement the selected-case workspace. The browser
uses explicit HTTP commands and three safe query endpoints. Pending start
identity and the selected-case URL support ambiguous-response recovery and
refresh; browser state is not a database.

Vitest covers API/state/persistence/status behavior; Playwright exercises the
actual UI. [package.json](../../frontend/package.json) and
[package-lock.json](../../frontend/package-lock.json) are authoritative.
There are no AG-UI, CopilotKit, assistant-chat or SSE dependencies in this UI.

## Storage, packaging and hosting

PostgreSQL stores cases, approvals, intent/ledger, audit and verification.
MAF session/workspace state uses a separate table in the same database.
This is not a separate materialized projection store.

The [Compose stack](../../compose.yaml) supplies independent local PostgreSQL 16.
The backend and frontend [Dockerfiles](../../backend/Dockerfile) /
[frontend Dockerfile](../../frontend/Dockerfile) take repository-root build
contexts. Nginx serves the UI, authenticates requests and injects the API token
server-side. The public UI does not expose the private API credential.

[azure.yaml](../../azure.yaml) declares the separate Hosted direct-code service.
Its [requirements](../../infra/foundry-hosted/agent/requirements.txt) are
independently pinned for the Python 3.13 Responses adapter. Generated source
copies are not edited directly. `prepare_hosted.verify_code_archive` checks
exact source bytes/file set and platform hash while excluding local environments
and private caches.

Bicep describes the lane-owned resource topology. The release helper provides
an image-only, saved-preview update for existing apps and keeps Hosted deployment
separate. ACR image/tag locks and source identity are release evidence, not
assumed guarantees of an arbitrary mutable tag.

## Validation and observability boundaries

Pytest covers service, API, runtime, MAF integration, durability, projections,
release guards and archive safety. Ruff is the backend linter.
The native Python Foundry evaluator requires seven explicit passing scores
of one and independent exact JSON comparisons; it is not an LLM judge.

OpenTelemetry/Application Insights record safe operational spans. The API
owns its exporter, while the Hosted Responses SDK owns its provider.
Audit records in PostgreSQL are the business evidence; telemetry does not
replace them. Trace presence, content safety and complete parentage are distinct
checks, including the known API tool-parent limitation.

See [observability](../../observability/README.md),
[evaluation](../../evals/README.md) and the [dated ledger](issues-changes-fixes.md)
for the checks actually run and retained failure history.
