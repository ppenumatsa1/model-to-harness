# Existing MAF deployment

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
API package downloads use the approved HTTPS mirror
`https://packagefeedproxy.microsoft.io/pypi/simple/`. The API Docker build honors
the default uv index and artifact URLs in the lane-owned manifest/lock.
The mirror supplies Microsoft Azure
Artifacts download URLs; the lock contains no original PyPI CDN downloads.
TLS verification stays enabled.

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
   resources, run `azd deploy model-harness-maf`, and verify the authoritative active
   version, environment, archive hash, and prepared package contents. Foundry can
   reuse an existing version when the uploaded source is identical; a version
   number alone is not source verification.

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

## Update an already migrated deployment

For subsequent releases, explicitly select `--update-existing` with the schema
already configured on the API. Preview and apply verify that schema's complete
migration history and checksums through a read-only connection. Missing, legacy,
changed, or pending migrations stop the release before any cloud mutation.
This mode does not create, migrate, adopt, or reset a schema; it is not a bypass
for the fresh-cutover guard. Apply any future reviewed SQL migration explicitly
before using it.

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  scripts/deploy_azure.sh --preview --update-existing --environment maf-dev \
  --schema maf_double_charge_cutover
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  scripts/deploy_azure.sh --apply --update-existing --environment maf-dev \
  --source-commit "$(git rev-parse HEAD)" --schema maf_double_charge_cutover
```

The remaining source, IaC, immutable-image, private-ingress, and readiness gates
are unchanged. Preview is still read-only; apply creates new image tags and deploys
the hosted bundle, preserving all workflow records and checkpoints. Identical-code
version reuse is accepted only after archive and environment verification.

## Explicit acceptance

```bash
scripts/smoke_azure.sh --base-url https://THE-EXISTING-MAF-FRONTEND
.venv/bin/python scripts/e2e.py --base-url https://THE-EXISTING-MAF-FRONTEND
scripts/e2e-browser.sh --base-url https://THE-EXISTING-MAF-FRONTEND
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  .venv/bin/python scripts/hosted_harness.py --environment maf-dev --version ACTUAL_VERSION
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  .venv/bin/python scripts/prepare_hosted_eval.py --environment maf-dev --version ACTUAL_VERSION
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

### Explicit SDK acceptance transport

If the local azd extension cannot acquire its token, select the documented
[Projects SDK session lifecycle](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-sessions?pivots=python)
and agent-bound Responses client explicitly:

```bash
AZURE_TOKEN_CREDENTIALS=AzureCliCredential \
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  .venv/bin/python scripts/hosted_harness.py \
  --environment maf-dev --version ACTUAL_VERSION --transport sdk
```

This is not an automatic fallback or a retry of an uncertain business command.
The same seven assertions run against the same deployed hosted entrypoint.
The SDK verifies the selected active version, creates a version-pinned owned
session and a new conversation per command, and stops the session in `finally`.
SDK HTTP retries are disabled; session-readiness polling does not invoke commands.
Clients and credentials close deterministically. The local credential choice does
not modify azd's global authentication settings or the deployed managed identity.

The installed azd agent extension intermittently failed with
`AzureDeveloperCLICredential: signal: killed`. Its Go credential has a default
10-second subprocess deadline when no caller deadline exists; that mechanism is
consistent with the symptom, not a proven root cause. Delegated Azure CLI auth was
already enabled and token prewarming did not fix it. The explicit Python transport
avoids that nested azd credential path without upgrading tools, weakening TLS, or
changing application code.

### Pinned hosted evaluation acceptance

`scripts/prepare_hosted_eval.py` is the pinned acceptance setup path. It reads the
selected azd environment as JSON, verifies the requested active hosted version
with the Projects SDK `agents.get_version`, and verifies both catalog versions
before creating **one fresh evaluation group only**. It never starts an evaluation
run, invokes the agent, updates `LAST_EVAL_ID`, or reuses a historical group ID.
The context-managed `DefaultAzureCredential` supports local credential selection;
SDK mutation retries are disabled.

The reviewed `agent/eval.yaml` pins task completion 19 and relevance 12. The helper
uses short criterion names, `builtin.*` evaluator names, and both `model` and
`deployment_name` from `options.eval_model`. It maps query to `{{item.query}}`,
response to `{{sample.output_items}}`, and includes the tool-call/tool-definition
mappings. Its permissive custom source schema (`item_schema: {}`,
`include_sample_schema: true`) matches the validated cloud configuration; strict
local checks retain all four reviewed case contracts before any cloud mutation.
Only case and idempotency IDs are freshly allocated. Complaints, ground truth,
expected outcomes, and default evaluator thresholds are not rewritten.

Setup prints only a safe summary and the path to a private `batch-request.json`
under ignored `.azure/release/hosted-eval-*` (directory 0700, files 0600). That file
contains the exact arguments for **`evaluation_agent_batch_eval_create`**, including
the new `evaluationId`, verified `agentVersion`, and all four `inputData` rows.
Submit that request through the Foundry MCP tool; setup itself does not submit it.
The same directory retains the definition, input data, and group receipt. Treat
these as private operational artifacts: never paste their prompts into public
reports or commit them. If setup fails after group creation, inspect the receipt
before retrying; a client error does not prove that no group was created.

The installed azd agent extension beta12 parses evaluator objects but its
[`eval run` builder](https://github.com/Azure/azure-dev/blob/azd-ext-azure-ai-agents_1.0.0-beta.12/cli/azd/extensions/azure.ai.agents/internal/pkg/agents/eval_api/eval_config.go)
ignores evaluator versions and initialization overrides. Noninteractive runs may
also reuse the environment's `LAST_EVAL_ID` without updating its criteria.
Therefore neither `azd ai agent eval run` nor the older no-job
`bind_hosted_eval.py` is the pinned acceptance path.

After the MCP run, retrieve every result row with
`scripts/download_eval_results.py`, passing `--expected-items 4`; a completed run
alone is not a pass. The four-case single-turn suite covers two no-refund
complaints, a durable approval pause, and explicit bounded-read failure. Only the
multi-command harness tests approval/refund completion. Neither gate substitutes
for browser or telemetry verification.
