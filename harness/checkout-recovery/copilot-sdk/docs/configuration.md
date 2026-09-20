# Local configuration

The editable checkout reads only this lane's root `.env`. Explicit Settings/test
arguments override process environment, which overrides that file. Installed and
Hosted packages use environment configuration, not sibling dotenv discovery.

Use `.env.example` for supported names. The namespace is `CHECKOUT_COPILOT_`.
Default development mode is explicitly `scripted`; `copilot` requires a Foundry
project endpoint and model deployment. Production requires durable PostgreSQL
and, for the API, its authorization token.

| Setting | Local default / requirement |
| --- | --- |
| `CHECKOUT_COPILOT_API_HOST` | `127.0.0.1` |
| `CHECKOUT_COPILOT_API_PORT` | `8030` |
| `CHECKOUT_COPILOT_FRONTEND_ORIGIN` | `http://127.0.0.1:5180` |
| `CHECKOUT_COPILOT_DATABASE_URL` | No credential-bearing source default |
| `CHECKOUT_COPILOT_EXECUTION_MODE` | `scripted` or `copilot`; no runtime fallback |
| `CHECKOUT_COPILOT_TRACE_FIXTURE_CONTENT` | `false`; opt in only for synthetic acceptance |
| `CHECKOUT_COPILOT_TRACE_FILE` | Unset; development-only sanitized receipts, 32 MiB per file |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Empty disables API/native Azure export locally |

The database-only Compose stack binds PostgreSQL to loopback port `45432`.
Generate a private `.env.compose` password, then:

```bash
docker compose --env-file .env.compose up -d --wait postgres
uv run python scripts/with_local_db.py -- uv run python scripts/migrate.py --apply
uv run python scripts/with_local_db.py -- uv run pytest
```

The wrapper explicitly selects the lane-owned database and scripted test mode;
it disables Azure telemetry and refuses a different Compose database contract.
Do not use it to claim real-model acceptance.

Each repository pool has four connections and a 30-second acquisition timeout.
An active Start holds its transaction/case lock during bounded investigation
(up to 120 seconds). This preserves command atomicity, but limits concurrent
commands and queries; this educational deployment is not a high-throughput worker
queue. Pool acquisition failure is not a successful command; retry the same
Start UUID after capacity is available rather than creating another case.

Keep private configuration mode `0600`; never print secrets, source dotenv files
as shell code, or expose environment variables through frontend build definitions.

Local Python dependencies resolve through the Microsoft package feed declared
in `pyproject.toml`; `uv.lock` is authoritative for that laptop profile. npm uses
`frontend/.npmrc`. Production API images and Foundry Hosted builds instead use
hashed public-PyPI pins from `requirements-cloud.lock`; `.venv-cloud` validates
that set independently. See the [delivery contract](../infra/README.md).

For the verified azd provider, `azd provision` emits `FOUNDRY_PROJECT_ENDPOINT`.
Bind its validated value to the lane's `AZURE_AI_PROJECT_ENDPOINT`, and explicitly
set `CHECKOUT_COPILOT_FOUNDRY_MODEL_DEPLOYMENT` and
`CHECKOUT_COPILOT_MAX_AUTO_INVENTORY_QUANTITY` before release preparation. The
verified deployment uses `gpt-4.1-mini` Standard100 and quantity `1`.
Run release helpers as `.venv-cloud/bin/python scripts/release.py ...`.

Browser Basic login is temporarily disabled by default for the public demo.
Set the frontend's `CHECKOUT_UI_AUTH_ENABLED=true` to restore it; only then is
`CHECKOUT_UI_HTPASSWD` required. Internal API tokens, upstream TLS, managed
identities, and explicit durable approval commands remain unchanged.
Anyone with the UI URL can read cases and issue commands; reviewer labels are
not verified identities. Restore login before non-demo use. Run anonymous smoke
and E2E without `CHECKOUT_UI_USERNAME` / `CHECKOUT_UI_PASSWORD`.

Successful GET/HEAD/OPTIONS API spans are omitted to remove health-check and
selected-case polling noise. Commands, model/tool spans, and failed requests
remain. Historical telemetry is not deleted.

The selected SDK/runtime pair is SDK `1.0.13`, explicitly provisioned native runtime
`1.0.85`, protocol `3`. SDK `1.0.13` defaults to runtime `1.0.83`; do not use that
implicit default or an unqualified runtime download. Packaging and startup verify
the selected runtime. Existing SDK `1.0.14` native archives are retained unchanged;
business Resume does not require converting them.
