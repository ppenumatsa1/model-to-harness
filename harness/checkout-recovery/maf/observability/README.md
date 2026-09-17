# Safe telemetry operations

PostgreSQL is the authority for checkout state, approvals, remediation
idempotency, audit records, and verification. App Insights and Log Analytics are
operational evidence only; no sampled or retained trace proves exactly-once
side effects.

## Export ownership and redaction

The API Container App receives the App Insights connection string as a Bicep
secret. Configure only allowlisted operational event names and correlation keys
in the application; do not capture prompts, request or response bodies, tool
arguments/results, connection strings, credentials, checkpoint payloads, or
exception text. Use a deterministic hashed business correlation key if a
case/run join is needed.

The Foundry Hosted Agent remains on the platform's OpenTelemetry provider and
exporter. The adapter must not call an Azure Monitor distro setup method, create
a tracer provider, or shut down platform telemetry. `azure.yaml` sets
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` before host startup.
Do not set an App Insights connection string in the hosted-agent environment.

## Post-deployment verification

After an operator has run `scripts/verify_hosted.py` for a specific agent version,
replace the placeholders in [safe-commands.kql](safe-commands.kql). Verify each
command request is correlated with safe attributes only. Review durable audit
records separately for approval and remediation correctness. Empty telemetry,
missing ingestion, or trace sampling is an operational failure; it must never be
papered over by enabling content capture or replacing the platform provider.

The API exporter in `infrastructure/telemetry.py` retains every span it receives,
including native MAF tool/agent/model intermediates and unknown instrumentation.
Original trace IDs, span IDs and parent IDs survive unchanged across export
batches: it neither drops intermediate parents nor invents replacement parents.
It cannot reconstruct parents never received because of upstream sampling or
instrumentation gaps.

Only exact allowlisted application names survive. Native `execute_tool`,
`invoke_agent`/`create_agent`, and `chat`/`embeddings` operation attributes select
fixed `checkout.native.tool`, `.agent`, and `.model` names; all other names become
`checkout.native.span`. Dynamic tool, agent and model names never pass through.
Allowed attributes are the fixed `checkout.component=maf`, a 24-character
lowercase hexadecimal `checkout.correlation` hash, and the enumerated native
`gen_ai.operation.name`. Events, links, instrumentation scope, trace-state,
exception descriptions and all other attributes are removed. The resource is
exactly `service.name=checkout-recovery-maf-api`; resource environment variables
and detectors cannot append content. Timing, span kind and status code remain.
`checkout.model` measures the bounded model/tool invocation loop, not a
billing-grade span for each individual inference.

`configure_api_telemetry(connection_string=selected_value)` accepts the API's
resolved configuration directly. An explicit `None` or empty string disables
setup even if `APPLICATIONINSIGHTS_CONNECTION_STRING` is present; the legacy
no-argument call still reads that environment variable. Disabling setup does
not remove an already-installed provider. `operation(name, case_id=None)` remains
the application instrumentation interface. Hosted must not call API telemetry
setup and continues to use the SDK-owned provider.

This configuration is **trace-only**: it installs no logging provider, logging
handler, log exporter or Azure Monitor distro auto-instrumentation. Do not enable
SDK message/tool content capture or log prompts, plans, tool arguments/results,
raw exceptions or credentials. The span scrubber does not sanitize stdout,
existing log handlers or platform-owned Hosted telemetry; their content capture
must remain disabled independently.

Focused [telemetry tests](../backend/tests/test_telemetry.py) exercise the installed
MAF native tool-span helpers, the three diagnostic tool parent edges, child-first
export across batches, unknown intermediates, and metadata/content redaction.
These local checks do not assert a new deployment or ingestion result.

The deployed `crmaf-20260912` acceptance run confirmed API and Hosted harness,
model-loop, tool, approval, remediation, and verification spans. The scoped
[acceptance](acceptance.kql) and [redaction](redaction.kql) queries are recorded
with observed counts in the [delivery ledger](../docs/design/issues-changes-fixes.md).
