# Native investigator boundary

`CopilotInvestigator(endpoint, deployment)` owns one async credential, local
telemetry receiver, native CLI process, and isolated private directory per call.
Authentication refreshes through an async Entra callback for
`https://ai.azure.com/.default`; neither GitHub login nor a PAT is required.
`ScriptedInvestigator` is explicit offline mode, never a fallback.

`fixture_content=True` opts in only the Python `read_order`, `read_payment`, and
`read_inventory` spans, including the child's inventory read. The telemetry
helper validates exact known synthetic status/amount/quantity payloads before
recording canonical results and empty arguments. Logs, plans, delegation output,
prompts, and freeform model output are never captured. Native content capture
remains disabled even when this diagnostic flag is enabled.

The approved-feed SDK trial pins **1.0.13**, independently selected runtime
**1.0.85**, and protocol **3**. SDK 1.0.13's default runtime is 1.0.83 and must
not be selected implicitly. Provision the runtime separately with
`python -m copilot download-runtime --version 1.0.85`; private case state
must not contain the binary cache. The resolver supports the pinned SDK's hostless
wrapper cache as well as its legacy executable alias.
`COPILOT_CLI_EXTRACT_DIR` uses the upstream cache layout; an explicit absolute
`COPILOT_CLI_PATH` is also supported. Native version/protocol checks still run
before session creation. The investigator never downloads a missing runtime.

The provider's `wire_model` is the configured Foundry deployment. Its `model_id`
is the explicit read-only runtime profile `checkout-recovery-readonly`, with
16,000 prompt tokens and 2,000 output tokens. This separates inference routing
from coding-model presets: runtime 1.0.85 otherwise injects unsupported
`reasoning.effort` for `gpt-4.1-mini`, even with reasoning capabilities disabled.
Reasoning summaries are disabled; no request-body rewriting proxy is involved.

## Capabilities and limits

Only the native `checkout-triage` skill and seven named custom tools are offered.
The custom tools read synthetic case evidence, write/read a bounded `plan.md`, or
delegate inventory once. The delegated worker is a **real bounded child Copilot
session**, not a built-in custom agent or a deterministic substitute. Its only
capability is `read_inventory`. Both sessions share the counters and deadline.

Configuration, user instruction, extension, plugin, host Git, file-hook, and
on-demand instruction discovery are disabled. All native permission requests are
rejected. Shell, general filesystem, web, MCP, business-write, and built-in agent
tools are absent. A pre-tool hook additionally denies unknown tools, unknown
skills, and calls exceeding **24 total tools**.
The child's hook independently permits only `read_inventory`, while sharing
the aggregate counter with the parent.

Native subprocesses inherit only the explicit HTTP(S) proxy and certificate-path
transport allowlist, not ambient Azure/GitHub/OpenAI credentials or Node options.
Proxy URLs must not contain credentials; loopback is always added to `NO_PROXY`
so the local telemetry receiver is never routed through an outbound proxy.
Lowercase `http_proxy`, `https_proxy`, and `no_proxy` are accepted. If both cases
are configured, uppercase takes precedence, including an explicitly empty value
that disables the corresponding lowercase proxy. Selected values are forwarded
identically in both forms; both bypass lists always include loopback.

The **120-second** work deadline cancels the SDK task, aborts sessions, then shuts
down the owned CLI. Cleanup gets a separate bounded grace period before force
stop and process reaping. Late handlers and token callbacks are closed. Native
skill invocation, successful native tool completions, and workspace write/read
must all be observed; final model prose is not evidence.

The pinned SDK has **no pre-model hook or hard model-request counter**. The
**12 observed attempts** budget counts new turns and retry notifications together
across parent and child sessions. Evidence records turns, retries, and their
aggregate separately; retries are not mislabeled as new turns.
It is not an exact HTTP request ceiling, especially for internal retries or
native compaction. Infinite-session history/compaction remains SDK-owned.

Primary investigation failures survive secondary cleanup errors; cleanup errors
are logged using only the fixed cleanup phase and exception class.
`framework_state.evidence.telemetry_export_failed` is sampled after CLI shutdown
and receiver drain. A reported export failure is distinct from investigation
success and does not discard an otherwise valid durable archive.

## Adapter cancellation

`sdk.cancellation.cancellation_scope(threading.Event)` binds an explicit
cross-thread signal through a `ContextVar`. Bind before scheduling `to_thread`;
on request cancellation, the adapter must set that event and await worker cleanup
rather than only cancel the `to_thread` waiter. The investigator monitors the
signal at 50 ms intervals and at tool/token boundaries, cancels the async native
invocation, and aborts/force-stops its owned runtime. After cleanup, synchronous
`investigate()` normalizes explicit signal cancellation to
`InvestigationIncompleteError("Copilot investigation cancelled")`, preserving
the application's existing durable failed-Start path. Cooperative cancellation emits only the fixed
`failure_kind=investigation_cancelled` diagnostic, without exception payloads.
Unrelated async task cancellation remains `CancelledError`. Monitoring is disarmed during cleanup
to avoid a second cancellation interrupting process teardown. This SDK mechanism
does not change application transactions or business Resume semantics.

## Private continuity

After successful completion, disconnection, and process shutdown, `archive.py`
copies the native session subtree unchanged into a size-bounded, base64 archive.
It does not interpret, summarize, or manufacture a transcript. The application
persists this object in its private PostgreSQL JSONB row within the case
transaction. Global configuration and credentials are outside the archive.
Path traversal, symlinks, unknown root files, credential-like filenames, oversized
archives, and version mismatches fail closed.
Historical SDK 1.0.14 archives and receipts remain unchanged. There is no
cross-version archive conversion or relaxed compatibility guard. Business Resume
does not consume these archives.
Durable native state is a mandatory completion boundary: snapshot/format failure
fails investigation before business remediation. Its non-authoritative role in
business decisions does **not** make archive persistence optional or best-effort.
`archive.validate(state)` runs the same pure archive validation used by restore
and returns detached session IDs without filesystem access, for private database
audits that must not recreate conversational payloads.

`resume_native(simulator, framework_state)` is a private diagnostic/probe helper:
it restores native files into a fresh directory and calls `resume_session` with
the provider, tools, hooks, and permissions restored. Business **Resume** never
uses this helper or depends on conversational history. In-flight exact-turn
recovery is not promised.

The local probes exercise the real pinned CLI against a scripted Responses HTTP
peer, including native skill execution, child execution, native history reaching
the model after fresh-directory restore, and error/timeout process cleanup.
They do **not** constitute Azure model acceptance; `--azure` is a separate
explicit probe mode. New trial receipts contain only fixed metadata under
`.acceptance/sdk-1.0.13/`, separate from historical SDK 1.0.14 evidence.

`scripts/probe_copilot_acceptance.py` is the separate inference-only Foundry
probe. It uses the lane's private settings and Azure CLI identity, runs initial
and resumed work in distinct Python/CLI processes, and verifies recall of a
synthetic marker absent from the second prompt. Its `.acceptance/` directory must
be git-ignored. The native archive is removed after the test; only bounded
receipts and sanitized native spans remain. No cloud resources are created.
