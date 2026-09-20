# Technology stack

| Component | Purpose |
| --- | --- |
| Python 3.13 | Application and Hosted runtime |
| GitHub Copilot SDK and its pinned native runtime | Model/tool loop, skills, session/context features |
| Azure Identity | Local Entra credentials and hosted managed identity |
| Foundry Responses transport | Explicit Hosted command adapter |
| FastAPI / Pydantic | Typed API commands and safe response contracts |
| Psycopg / PostgreSQL | Durable case, approval, intent, audit and private framework storage |
| React / Vite | Independent selected-case workspace |
| OpenTelemetry / Azure Monitor | Application spans and sanitized native CLI telemetry |
| pytest / Vitest / Playwright | Backend, UI and browser acceptance |
| Bicep / azd / containers | Independent cloud and application delivery |

[Python dependencies](../../pyproject.toml), the lockfile,
[frontend dependencies](../../frontend/package.json), and lane deployment
configuration are authoritative. Do not add MAF dependencies or import the POC.
Local scripted tests, real-model runs and deployed acceptance are distinct gates.
