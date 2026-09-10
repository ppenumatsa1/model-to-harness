# Existing MAF deployment cutover

This lane owns its Container Apps, ACR, PostgreSQL configuration and Foundry
integration independently of LangGraph. The API stays private; the public nginx
frontend proxies `/api/` and health requests to it on the same origin. Hosted
Responses remains **direct Python 3.13 code deployment**, not an ACR container.
The API image uses pinned uv `0.11.2` and `uv sync --frozen --no-dev --no-editable`
in the repository-relative layout, then copies only the installed environment into
the runtime image. Its framework versions come from `uv.lock`; hosted requirements
pin the same tested core `1.16.0`, Foundry `1.11.0`, framework-OpenAI `1.14.1`,
Projects SDK `2.3.0` and OpenAI client `2.54.0` versions.
Hosted platform distro `microsoft-opentelemetry==1.3.9` supports the tested OTel
`1.44` family; the SDK initializes its provider before MAF adds safety processors.
The API's Azure Monitor distro is not installed as a competing hosted provider.
The SDK content-capture flag is forced to `false` before host construction and is
also declared in `azure.yaml`; inherited local settings cannot enable prompt capture.

The local/API uv configuration and frontend builds use the approved Microsoft
package-feed mirrors. Hosted `remote_build` requirements intentionally leave the
platform's default PyPI index unchanged: the Foundry builder failed TLS resolution
when forced through the mirror. Package versions remain pinned as above; TLS
verification is never disabled.

## Local release gates and preview

Run from the MAF lane, using the parent's reviewed, tested source commit. Supply
CLI user-agent guidance in the calling environment when required; scripts never
persist it in azd settings.

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  scripts/deploy_azure.sh --preview --environment maf-dev \
  --schema maf_double_charge_cutover
```

Preview resolves azd JSON settings, existing deployment outputs, current images and
schema, ACR, PostgreSQL and Foundry identity. It prints sanitized final parameters
and ARM resource change types, not credentials. It never creates resources, builds
images, migrates SQL, deploys code, or resets data. A dirty-tree preview is explicitly
marked; it does not claim those sources were validated at HEAD.

The existing `DATABASE_URL` must match the existing MAF PostgreSQL host and password.
The release does not generate passwords or replace servers. `--operator-ip` explicitly
changes the operator firewall; omitting it preserves the existing configured value.
Preview reports PostgreSQL's current state; apply requires `Ready`. An operator must
explicitly start a stopped server and wait for readiness before applying this release.
Foundry project/model settings must already exist. There is no automatic
`azd provision` or resource deletion.

## Ordered apply (operator only)

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  scripts/deploy_azure.sh --apply --environment maf-dev \
  --source-commit "$(git rev-parse HEAD)" --schema maf_double_charge_cutover
```

1. Require a clean selected HEAD for all MAF/shared runtime and build-context sources.
2. Show final parameters and ARM what-if before any mutation.
3. If infrastructure changes are reported (or `--foundation` is supplied), apply
   them **with existing app images, target port and schema**; await healthy revisions.
4. Explicitly execute the versioned SQL runner with `--require-empty` against the
   new schema in the existing database. No runtime performs migrations or resets.
5. Build only archived committed sources into unique commit-prefixed ACR tags and
   lock those images against overwrite/deletion.
6. Apply new app images/schema and await successful, ready revisions.
7. Set the nonsecret hosted schema/project endpoint, prepare source plus SQL
   resources, run `azd deploy model-harness-maf`, and await a **new active version**.

Restricted ARM parameter files (0600 in 0700 directories) and source archives live
under ignored `.azure/release/` and are removed even on failure. Secrets are passed
through restricted files or subprocess environments, not command arguments.
Captured CLI output is never dumped on failure. A failed gate stops the release;
there is no automatic rollback, schema purge, or legacy checkpoint support.
If migration succeeds but a later step fails, the operator must inspect that schema
before a deliberate recovery; `--require-empty` intentionally rejects blind reruns.
If only hosted deployment fails after the app rollout, inspect the actual attempted
version with the Projects SDK; azd can still select the previous active version.
Retry only the hosted deployment from a clean validated source snapshot, preserving
the already-migrated schema and application images. A dependency-index-only hosted
fix does not change the deployed API/frontend runtime source.

## Explicit acceptance

```bash
scripts/smoke_azure.sh --base-url https://THE-EXISTING-MAF-FRONTEND
.venv/bin/python scripts/e2e.py --base-url https://THE-EXISTING-MAF-FRONTEND
scripts/e2e-browser.sh --base-url https://THE-EXISTING-MAF-FRONTEND
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  .venv/bin/python scripts/hosted_harness.py --environment maf-dev --version ACTUAL_VERSION
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  .venv/bin/python scripts/bind_hosted_eval.py --environment maf-dev --version ACTUAL_VERSION
```

Cloud browser mode never starts a local API or Vite server. API and hosted harnesses
use unique case/idempotency IDs and explicit start, approval, then resume commands.
They cover no duplicate, approval/refund, denial, retry, resumed approval, failure
and manual review. The hosted harness parses the installed CLI's raw HTTP/Responses
JSON or completed SSE response, never assumes command startup means success, and
uses explicit versions and new sessions/conversations.
Each hosted command creates a uniquely named harness-owned session and stops its
compute in a `finally` block, including failed invocations. This releases its
PostgreSQL pool instead of accumulating live sessions until the small teaching
server runs out of connections. Workflow state survives in PostgreSQL; approval
and resume still run in separate fresh sessions.
The hosted adapter binds SDK conversation/response IDs and workflow case/run IDs
through the MAF-local safe telemetry context. It hashes telemetry join keys
and annotates the existing platform span without introducing another span/provider.
Absent platform conversation/response IDs are omitted, not fabricated.
Approval/resume loads durable state before execution so command scopes use the
authoritative case/run IDs, including when the command subsequently fails.
The raw framing was checked against installed CLI help and the public
[Responses invoke writer](https://github.com/Azure/azure-dev/blob/main/cli/azd/extensions/azure.ai.agents/internal/cmd/invoke_raw.go):
HTTP headers are followed by decoded body bytes, not HTTP transfer-chunk framing.

The evaluation binder retains seed intent, adds unique IDs and writes an ignored
config bound to the verified active version. It **does not create evaluation jobs**.
Run the emitted config with `azd ai agent eval run --config PATH --environment maf-dev`,
then retrieve every result row with `scripts/download_eval_results.py`. The
single-turn suite tests no-refund, durable approval pause and explicit failure;
only the multi-command harness tests approval/refund completion. Neither gate
substitutes for browser or telemetry verification.
