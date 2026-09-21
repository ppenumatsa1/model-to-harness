# MAF technology stack

This lane owns its runtime and dependency manifests. See
[architecture](architecture.md) for responsibilities and
[project structure](projectstructure.md) for source locations.

## Backend and contracts

| Technology | Role and source of truth |
| --- | --- |
| Python 3.12, Hatchling, uv | Local/API runtime, wheel packaging, locked dependencies in [pyproject.toml](../../pyproject.toml) and [uv.lock](../../uv.lock). |
| Microsoft Agent Framework | Core `1.16.0`, Foundry adapter `1.11.0` in the current manifest: explicit graph, native executors, fan-out/fan-in, information requests, checkpoints and model integration. |
| FastAPI, Uvicorn | MAF-owned HTTP command/read/stream contracts and canonical API entrypoint. |
| Pydantic v2, pydantic-settings | Typed commands/state and explicit Settings precedence. Source-layout-checked lane dotenv for editable execution; no installed-parent scanning. |
| Psycopg 3, PostgreSQL | Authoritative runs/events/approvals/memory/outcomes, framework-owned checkpoint adapter and durable simulated refund ledger. |
| Azure Identity | Configured model adapter's identity boundary; no embedded key/credential default. |
| OpenTelemetry, Azure Monitor | Optional API export and SDK-owned hosted instrumentation; safe native traces are operational evidence, not workflow authority. |
| `model-to-harness-shared` | Editable local dependency containing only domain, deterministic simulators, fixtures and normalized evaluation contracts. |

The shared package uses decimal money, aware timestamps and validated domain
records. It does not supply MAF orchestration, API, persistence, telemetry or
cloud clients. No framework upgrades are part of this configuration/docs change.

## Frontend

[package.json](../../frontend/package.json) and
[package-lock.json](../../frontend/package-lock.json) define React 19,
TypeScript, Vite, CopilotKit, Vitest/Testing Library and Playwright dependencies.
The three-pane workspace and business audit are MAF-owned React components;
native SSE and HTTP snapshots supply durable data. CopilotKit uses a real
read-only selected-run AG-UI runtime.

Vite's server config reads only the selected lane `.env` and returns an allowlist
of port/proxy values. It uses Node's `util.parseEnv` (Node 20.12+; the pinned Vite 7
toolchain has the stricter Node 20.19+ / 22.12+ requirement). No new dotenv package,
client secret prefix or broad environment define is introduced. Production builds
do not load dotenv. Nginx provides the deployed same-origin proxy.

## Storage, packaging and hosting

Local PostgreSQL 16 may be supplied by the root developer-only Compose dependency;
MAF owns its schema and explicit SQL runner. Runtime startup verifies readiness
without DDL. The dedicated integration target is loopback port 5434 and database
`maf_cutover_tests`, never an ordinary application database.

Lane IaC describes separate public frontend/private API Container Apps, MAF ACR,
PostgreSQL Flexible Server, Foundry project/model, managed identities and
Application Insights/Log Analytics. Hosted Responses 2.0 uses direct Python 3.13
code deployment with [independent requirements](../../infra/foundry-hosted/agent/requirements.txt),
not the API container environment. Generated hosted package and SQL copies are
artifacts, not maintained duplicate source.

Approved Microsoft package mirrors remain configured for local/API Python and
frontend builds. Hosted remote dependency resolution retains its platform default
index after the historical mirror failure; TLS is never disabled. See
[infra guidance](../../infra/README.md) for exact packaging and release controls.

## Validation and observability boundaries

Pytest/Ruff exercise the backend, scripts and evaluation contracts. In-memory
fakes run without cloud settings; real PostgreSQL tests explicitly require the
dedicated test URL and create only their isolated schemas. Frontend tests and
mocked browser checks exercise selection, live updates and safe audit views.
The seven deterministic local evaluations are separate from Foundry judge jobs.

Keep dependency pins in manifests/locks rather than copying a complete version
inventory into documentation. Hosted version 8 and its earlier judge results are
historical evidence, not proof that today's checkout, private configuration,
local UI or remote resources have passed current acceptance. See the
[ledger](issues-changes-fixes.md) and [observability setup](../../observability/SETUP.md).
