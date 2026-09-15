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

The API exporter in `infrastructure/telemetry.py` admits only fixed `checkout.*`
spans and allowlisted hashed correlation/component attributes; it strips events,
links, unrelated resource attributes, and exception descriptions. The Hosted
adapter uses the platform provider instead. `checkout.model` measures the bounded
model/tool invocation loop, not a billing-grade span for each individual inference.

The deployed `crmaf-20260912` acceptance run confirmed API and Hosted harness,
model-loop, tool, approval, remediation, and verification spans. The scoped
[acceptance](acceptance.kql) and [redaction](redaction.kql) queries are recorded
with observed counts in the [delivery ledger](../docs/issues-changes-fixes.md).
