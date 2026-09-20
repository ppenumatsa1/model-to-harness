# Local configuration and startup

This configuration belongs only to the checkout-recovery MAF lane. It does not
load another lane's settings or change Compose or Azure configuration.

## Backend settings

In an editable source checkout, `Settings()` selects exactly
`harness/checkout-recovery/maf/.env`, relative to its own source package, not the
current working directory. The file is optional. Discovery requires the lane's
`backend/src/checkout_recovery_maf` layout and `pyproject.toml`; installed packages
and the Hosted package layout do not discover dotenv files. Parent directories,
`.env.local`, `.env.production`, `.env.compose`, and `.azure` are never searched.

Precedence is explicit `Settings(...)` arguments, process environment, selected
dotenv file, then defaults. `Settings(_env_file=path)` explicitly selects a file;
`Settings(_env_file=None)` disables dotenv without disabling environment variables.
Tests and Hosted startup should pass `_env_file=None` explicitly. Settings loading
does not mutate process environment or initialize telemetry.

Existing `CHECKOUT_RECOVERY_` keys retain their meanings:

| Environment key | Default / purpose |
| --- | --- |
| `CHECKOUT_RECOVERY_API_HOST` | `127.0.0.1`; API bind IP address or hostname, no scheme or port |
| `CHECKOUT_RECOVERY_API_PORT` | `8000`; integer from 1 through 65535 |
| `CHECKOUT_RECOVERY_FRONTEND_ORIGIN` | `http://127.0.0.1:5173`; HTTP(S) origin without credentials, query, fragment, or path |
| `CHECKOUT_RECOVERY_ENVIRONMENT` | `development`; `production` retains fail-closed runtime validation |
| `CHECKOUT_RECOVERY_EXECUTION_MODE` | `scripted`; `maf` requires the project endpoint and model deployment |
| `CHECKOUT_RECOVERY_DATABASE_URL` | Unset; PostgreSQL connection string |
| `CHECKOUT_RECOVERY_API_TOKEN` | Unset; API authentication secret |
| `CHECKOUT_RECOVERY_FOUNDRY_PROJECT_ENDPOINT` | Unset; project endpoint for MAF execution |
| `CHECKOUT_RECOVERY_FOUNDRY_MODEL_DEPLOYMENT` | Unset; deployment name for MAF execution |
| `CHECKOUT_RECOVERY_MAX_AUTO_INVENTORY_QUANTITY` | `1`; existing remediation policy limit |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Unset; standard unprefixed telemetry key |

The telemetry field is `settings.applicationinsights_connection_string`, with
`APPLICATIONINSIGHTS_CONNECTION_STRING` as its validation alias. Explicit
snake-case constructor arguments retain highest precedence. API runtime wiring
must pass that selected value explicitly to telemetry configuration rather than
re-reading process environment: a selected dotenv value need not exist in
`os.environ`. Do not print settings or connection strings.

Production API execution requires PostgreSQL, an API token, and MAF execution.
Hosted execution requires PostgreSQL and MAF execution. This configuration change
does not initialize PostgreSQL, run migrations, or select a cloud environment.

## Local launchers

With the lane's existing editable Python environment and frontend dependencies
already installed, run these commands in separate terminals from the repository
root:

```sh
bash harness/checkout-recovery/maf/scripts/dev-backend.sh
bash harness/checkout-recovery/maf/scripts/dev-frontend.sh
```

The scripts locate their own lane regardless of the caller's working directory.
The backend script uses the lane's `.venv/bin/python`; the frontend uses `npm run
dev` from its own directory. Neither installs packages or sources dotenv as shell
code. Alternatively, run `python -m checkout_recovery_maf` using the installed
Python environment, or `npm run dev` from the frontend directory.

The Python launcher selects one settings instance, validates it before starting
Uvicorn, and passes that same instance to the app factory. It uses `api_host` and
`api_port` without auto-reload. The existing
`uvicorn checkout_recovery_maf.main:create_app --factory` entrypoint remains valid,
but direct Uvicorn invocations need their own bind arguments; they do not use the
Python launcher's bind settings.

Temporary port overrides require no file edits:

```sh
CHECKOUT_RECOVERY_API_PORT=18020 \
CHECKOUT_RECOVERY_FRONTEND_ORIGIN=http://127.0.0.1:15175 \
bash harness/checkout-recovery/maf/scripts/dev-backend.sh

CHECKOUT_RECOVERY_API_PORT=18020 \
CHECKOUT_RECOVERY_FRONTEND_ORIGIN=http://127.0.0.1:15175 \
bash harness/checkout-recovery/maf/scripts/dev-frontend.sh
```

## Frontend configuration boundary

Vite reads only the selected lane `.env` for local development, with process
overrides. Its Node-only configuration consumes an allowlist of
`CHECKOUT_RECOVERY_API_HOST`, `CHECKOUT_RECOVERY_API_PORT`, and
`CHECKOUT_RECOVERY_FRONTEND_ORIGIN`. Use literal values for these settings; the
frontend parser does not expand shell variables. Builds do not read this file.
Vite's automatic dotenv loading and client environment prefixes are disabled.
Neither settings nor dotenv contents are supplied through `define`, browser
imports, or `VITE_*` variables.

The development frontend accepts only a loopback **HTTP** origin (`127.0.0.1`,
`localhost`, or `[::1]`). Its port is strict: a collision fails instead of silently
selecting another port. API wildcard bind addresses are translated to their
loopback proxy targets. Browser requests remain same-origin `/api` requests.
The frontend origin setting is not a backend CORS policy or authentication grant.

Vite does not read or inject the API token. It is intended for loopback-only
development without API authentication; if the selected backend requires a token,
requests remain unauthorized. Use the nginx runtime for deployed environments,
not browser API tokens or a public Vite server.

Browser Basic login is temporarily disabled by default for the public demo.
Set the frontend's `CHECKOUT_UI_AUTH_ENABLED=true` to restore it, supplying the
existing `CHECKOUT_UI_HTPASSWD` secret. Anyone with the UI URL can read cases and
issue Start, Approval, and Resume commands; reviewer labels are not verified
identities. Private API tokens, managed identities, upstream TLS, and durable
business approval checks remain enabled. Restore login before non-demo use.

Successful GET/HEAD/OPTIONS API spans are omitted to remove health-check and
selected-case polling noise. Commands, model/tool spans, and failed requests
remain. Historical telemetry is not deleted.
Do not override Vite's bind host to expose it publicly.

## Focused validation

Run backend configuration tests with scratch paths inside the lane:

```sh
cd harness/checkout-recovery/maf
.venv/bin/pytest backend/tests/test_local_config.py --basetemp=.test-work/config
cd frontend
npm test
npm run build
```

Configuration tests use synthetic dotenv files and isolated settings, with no
database connections, runtime startup, or telemetry initialization. Frontend
configuration tests keep their scratch files under `node_modules/.config-tests`.
