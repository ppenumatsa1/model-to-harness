# LangGraph technology and configuration

Related: [architecture](architecture.md), [project structure](projectstructure.md),
[ledger](issues-changes-fixes.md).

## Dependency roles

| Technology | Actual role and source of versions |
| --- | --- |
| Python 3.12 | Local/backend container baseline; lane `pyproject.toml` and `uv.lock`. |
| LangGraph 1.x | `StateGraph`, native retries, reducers, interrupts and execution. |
| `langgraph-checkpoint-postgres` 3.1.2 | Native async saver and framework-owned checkpoint migrations. |
| FastAPI, Uvicorn, Pydantic v2/settings | HTTP commands, validated projections and configuration. |
| Psycopg 3 | Application repository/pool, command locks, migrations and native saver connection. |
| LangChain OpenAI, Azure Identity, HTTPX/aiohttp | Lane-owned Azure model client and credential/client lifecycle. |
| OpenTelemetry, optional Azure Monitor distro | Safe native execution telemetry and optional API export. |
| React 19, TypeScript, Vite, CopilotKit | Browser inspection and read-only selected-run projection. |
| Node 20.19+ or 22.12+ | Vite's supported runtime, including the native dotenv parser for server settings. |
| Pytest, Ruff, Vitest, Playwright | Offline contracts, isolated persistence, static checks and browser acceptance. |
| Hatchling | Independent wheel and packaged application SQL. |
| Python 3.13 hosted Responses SDK | Existing hash-pinned stack in `infra/foundry-hosted/agent`; not the local interpreter. |

Frontend versions live in `frontend/package.json` and `package-lock.json`; hosted
pins are separate from application ranges. No framework/SDK/dependency upgrade is
part of this configuration/documentation work. Shared Python contracts supply
deterministic domain behavior, not any application runtime.

## Backend configuration contract

Precedence is **explicit Settings constructor values > process environment >
selected dotenv > defaults**. `_env_file=path` selects an explicit alternative;
`_env_file=None` disables dotenv. Settings only recognizes the source checkout
layout `langgraph/backend/src/model_to_harness_langgraph` with its lane manifest,
then uses an absolute lane-root `.env`. It never searches the CWD, root,
neighbor lane or `.env.local`. Wheels and hosted copied packages have no default
dotenv lookup; they remain process-environment-driven. Cached application settings
require a restart after edits.

| Canonical variable | Default / meaning |
| --- | --- |
| `APP_ENV` | `local`; telemetry deployment environment. |
| `LOG_LEVEL` | `INFO`. |
| `HOST`, `PORT` | `127.0.0.1`, `8000`; local backend launcher bind, port 1-65535. |
| `DATABASE_URL` | Empty; required before real storage setup/startup. No credential-bearing fallback. |
| `LANGGRAPH_SCHEMA` | `langgraph_app_cutover`; application records. |
| `LANGGRAPH_CHECKPOINT_SCHEMA` | `langgraph_checkpoints_cutover`; native saver, distinct from app schema. |
| `CORS_ORIGINS` | `http://localhost:5173`; comma-separated browser origins. |
| `AZURE_OPENAI_ENDPOINT` | No default; required for real model runtime. |
| `AZURE_OPENAI_DEPLOYMENT` | No default; required for real model runtime. |
| `AZURE_OPENAI_API_VERSION` | `2024-10-21`. |
| `MODEL_TEMPERATURE` | Omitted; explicit value 0-1 only when deployment supports it. |
| `TELEMETRY_ENABLED` | `true`; local export still requires a connection string; explicit false disables local provider installation. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Empty; optional local API exporter configuration, resolved through Settings. |
| `OTEL_SERVICE_NAME` | `model-to-harness-langgraph`. |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | `false`; must remain disabled. |
| `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED` | `false`; must remain disabled. |

Real bootstrap validates missing storage/model configuration before exporter,
database or model construction. Storage setup requires the database URL, not
model settings. Explicitly injected audit/checkpointer/model doubles do not need
their real counterparts. Settings are not exported to the browser or copied into
`os.environ`; connection strings are excluded from the Settings representation.

## Frontend server-only configuration

`frontend/server-config.ts` reads exactly `langgraph/.env` using Node's dotenv
parser and selects only these keys. Process values override the selected file.
Vite has automatic dotenv/public environment loading disabled (`envDir: false`,
`envPrefix: []`), so even a `VITE_*` key in the lane file is not published.

| Canonical variable | Default / meaning |
| --- | --- |
| `FRONTEND_HOST` | `localhost`; Vite bind address. |
| `FRONTEND_PORT` | `5173`; port 1-65535 with strict binding rather than silent fallback. |
| `BACKEND_PROXY_URL` | Optional HTTP(S) origin without userinfo/path/query/fragment; proxies `/api`, `/health`, `/ready`. |
| `HOST`, `PORT` | If proxy override is absent, derive `http://HOST:PORT`; `0.0.0.0`/`::` binds connect through `127.0.0.1`. |

Use literal values for server fields. No backend secrets are copied into client
definitions, HTML, bundles or `import.meta.env`. Changing the frontend origin
also requires updating backend `CORS_ORIGINS` when using cross-origin requests.
Default browser URL is `http://localhost:5173`; default API is
`http://127.0.0.1:8000`. Container deployment commands and nginx configuration
remain independent of these development-server settings.

## Telemetry safety and SDK compatibility

Bootstrap passes the resolved Settings to telemetry configuration. API resource
labels, connection string and explicit off switch therefore respect dotenv and
process precedence. Safety checks run before exporter initialization and after
provider installation. Both resolved capture flags and original process flags
must be disabled; a constructor override cannot hide an unsafe SDK process flag.

Complete-retention sampling is fixed/verified, not a user-selected percentage.
Existing SDK process controls such as `OTEL_TRACES_SAMPLER`,
`OTEL_TRACES_SAMPLER_ARG`, `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS`,
`AZURE_TRACING_ENABLED` and exporter settings remain SDK-owned process variables;
arbitrary dotenv keys are not injected into the SDK environment. Hosted setup
checks actual complete sampling and actual requests/urllib3/HTTPX and Azure SDK
transport opt-outs. Setting `TELEMETRY_ENABLED=false` does not disable those
hosted safety checks or take ownership of its SDK provider.

API log export stays within the named lane logger. Raw prompts, complaint text,
model reasoning, credentials, checkpoints, idempotency keys and unrestricted
tool payloads are prohibited. See [observability](../../observability/README.md).

## Local commands and test isolation

After independently installing the lane and shared package and privately filling
`.env`, invoke `scripts/dev-backend.sh` by absolute or relative path from any CWD.
It resolves the lane, requires its `.venv/bin/python`, uses absolute source paths
and runs `python -m model_to_harness_langgraph.main`.

```bash
# From the repository root:
agent-framework/double-charge/langgraph/scripts/dev-backend.sh
npm --prefix agent-framework/double-charge/langgraph/frontend run dev
```

With the editable lane package installed, its absolute `.venv/bin/python` can run
`-m model_to_harness_langgraph.infrastructure.persistence.migrations --verify-only`
from any CWD. Omit `--verify-only` only for explicitly authorized initial setup;
never run setup/reset to fix a runtime configuration failure.

`TEST_DATABASE_URL` is a **test-only process variable**, never loaded from lane
dotenv. It must name a dedicated loopback PostgreSQL database. Integration tests
create/drop randomized application/checkpoint pairs, not deployed schemas.
Unit fixtures disable dotenv, clear application environment configuration, turn
telemetry off and block external Python socket connections. E2E/evaluation fake
factories explicitly use `_env_file=None` and `telemetry_enabled=False` even
outside Pytest. Telemetry tests only install mocked/in-memory providers.
Browser acceptance uses `E2E_BACKEND_PORT`/`E2E_FRONTEND_PORT` process overrides
(defaults 18000/15173), refuses occupied ports and explicitly targets its own fake
backend. These test-runner controls are not application Settings or dotenv keys.
