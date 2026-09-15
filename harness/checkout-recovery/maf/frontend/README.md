# Checkout recovery workspace

This frontend belongs only to the checkout-recovery MAF lane. It renders the
backend's safe case, audit-event, and workspace-artifact projections. The browser
never receives the backend API token, model prompts, raw checkpoints, tool
arguments/results, or provider credentials.

## Local development

Start the lane's backend separately at `http://127.0.0.1:8000`. Then, from this
directory:

```sh
npm ci
npm run dev -- --host 127.0.0.1
```

Vite proxies same-origin `/api` requests to that backend. Nginx and basic auth are
not needed for loopback-only development. Do not expose the unauthenticated Vite
server publicly. There are no `VITE_*` token or backend-host build variables.

Each successful command selects its case through `?case=<case-id>`. Refreshing
the page reloads all workflow state from the API, not browser-cached workflow
objects. An unresolved start retains only its fixture and random request ID in
session storage; **Retry start** reuses that ID, including after page refresh.
A successful start clears it, so the next deliberate start creates a new case.
Approval carries the selected case's approval request ID, reviewer ID, decision,
and reason. Approval and denial do not resume or apply remediation; **Resume
recovery** is a separate explicit command.

## Containers

Build both images from the **repository root**, not this directory:

```sh
docker build -f harness/checkout-recovery/maf/frontend/Dockerfile \
  -t checkout-recovery-frontend .
docker build -f harness/checkout-recovery/maf/backend/Dockerfile \
  -t checkout-recovery-backend .
```

The frontend's Dockerfile-specific ignore file allowlists its build inputs.
The backend image installs the shared domain package and this lane's package
under Python 3.13, runs as a non-root user, serves Uvicorn on port 8000, and
includes SQL migrations at `/app/migrations`. It does not copy or install other
framework lanes. Configure and migrate PostgreSQL through the backend deployment
workflow before serving requests.

The frontend listens on port **8080**. Supply these values as runtime secrets or
environment variables, never image build arguments:

| Name | Value |
| --- | --- |
| `BACKEND_HOST` | Private backend hostname only, without `https://`, port, or path |
| `CHECKOUT_API_TOKEN` | Backend API secret; token-safe ASCII characters |
| `CHECKOUT_UI_HTPASSWD` | One or more `username:password-hash` lines |

Generate the UI hash with a password prompt (for example,
`htpasswd -nB checkout-reviewer`) and store its output directly in the deployment's
secret store. Do not commit the hash or plaintext password. Bcrypt, Apache MD5,
and SHA-crypt htpasswd entries are accepted; plaintext entries are rejected.
Missing secrets or invalid configuration fail startup closed.

The entrypoint writes a restricted htpasswd file and renders nginx configuration
at startup, then removes secret variables from the nginx process environment.
Nginx authenticates both HTML and API routes with basic auth, injects
`X-Checkout-Token` only on the server-side proxy, and strips the browser's Basic
authorization header before forwarding. The backend uses HTTPS with its own
hostname as both `Host` and TLS SNI, and its certificate is verified. API commands
are not automatically replayed by nginx. `/healthz` is an unauthenticated,
frontend-only health probe and contains no workflow data.

Use HTTPS at the public ingress: basic auth is not safe over public plaintext
HTTP. Keep backend ingress private. The container's unauthenticated health probe
does not replace backend readiness or PostgreSQL health checks.

## Validation

```sh
npm test
npm run build
mkdir -p node_modules/.playwright-work
export TMPDIR="$PWD/node_modules/.playwright-work"
export PLAYWRIGHT_BROWSERS_PATH=0
npx playwright install chromium
npm run test:e2e
```

These settings keep browser binaries and scratch files inside this frontend.
Use the same `PLAYWRIGHT_BROWSERS_PATH` value for installation and execution.

Browser tests start Vite only; the backend must already be available on port
8000 with its deterministic fixtures and durable persistence configured. The
suite covers all seven fixtures, bound approval and separate resume, refreshed
pending/decided/closed cases, safe response-field allowlists, and an ambiguous
start-response retry that must not create a duplicate case.
Model-backed commands allow 150 seconds (the 120-second model budget plus
transport overhead). Each test allows six minutes so the ambiguous-response
scenario can also run a second deliberate start; assertions remain unchanged.

To test an existing deployment, export `CHECKOUT_E2E_BASE_URL` with its HTTPS URL
and `CHECKOUT_UI_USERNAME` / `CHECKOUT_UI_PASSWORD` from your secret environment,
then run `npm run test:e2e`. A remote base URL disables local server startup. The
same-origin frontend proxy supplies the backend token; **do not provide that token
to Playwright or the browser**. Browser traces/HAR and video are disabled to avoid
recording authentication headers; only failure screenshots are retained.

Tests create fixture cases and audit records, so point them at an environment
intended for acceptance testing. They do not delete durable evidence.
