# Foundry Hosted Agent adapter

This is a direct Python 3.13 code-deployment adapter for the Responses 2.0
protocol. It accepts exactly one JSON command per request:

```json
{"action":"start","fixture_id":"captured-payment-approved-remediation"}
```

Approval and continuation are separate durable commands:

```json
{"action":"approval","case_id":"<case-id>","approval_request_id":"<server-issued-request-id>","decision":"approved","reviewer_id":"<reviewer-id>","reason":"Reviewed business evidence"}
{"action":"resume","case_id":"<case-id>"}
```

The adapter lazily starts the same checkout-owned `bootstrap.create_runtime`
used by FastAPI, with `host="hosted"` and a PostgreSQL repository. Settings come
from `config.py`; the adapter explicitly selects MAF regardless of the development
default. Hosted requires PostgreSQL and MAF configuration but not the
API proxy token. It does not import the API factory, routers, or middleware.
Synchronous startup, commands, and shutdown run through `asyncio.to_thread`;
startup failures and host shutdown close the owned runtime exactly once.
It never runs SQL migrations, resets data, accepts
chat-derived decisions, or falls back to memory when the database setting is
absent. Outputs are the existing safe case projection only.

`scripts/prepare_hosted.py` copies the checked-in backend and framework-neutral
shared packages into this deployable source directory. It must run after the
source has been reviewed and before `azd deploy checkout-recovery-maf`.
`.agentignore` excludes local environments, credentials/configuration, and test
caches from the upload. After downloading a deployed version's code ZIP,
`scripts/prepare_hosted.py` exposes the read-only
`verify_code_archive(root, content, expected_hash)` check: pass this prepared
source directory, ZIP bytes, and the platform SHA-256 (bare hex or `sha256:`).
It returns `archive_sha256` and `files` only after verifying the digest, exact
canonical file set, and every file's contents. Only `main.py`, `requirements.txt`,
`README.md`, the optional `.agentignore`, and the two prepared package trees are
allowed; private/local artifacts, testing code, caches, and duplicate entries
are rejected. This check neither extracts the ZIP nor calls Azure.
Platform telemetry remains platform-owned; this adapter does not initialize or
replace an OpenTelemetry provider, and message-content capture is disabled before
host construction.

The start command optionally accepts a UUID `request_id` for retry identity.
An explicit session is pinned to a version when created: do not pass both
`--version` and `--session-id` to `azd ai agent invoke`.
Run `scripts/verify_hosted.py` from the lane root for all seven explicit-command
scenarios. `eval.yaml` covers start outcomes and durable approval pauses; it does
not impersonate a reviewer or automatically approve consequential actions.
The verified release uses the native Python evaluation group recorded in
`.foundry/agent-metadata.yaml`, with the `checkout_exact_contract` catalog identity.
See the lane README for registration, agent-target submission, and strict
per-item collection; a completed job or a missing score never counts as a pass.
