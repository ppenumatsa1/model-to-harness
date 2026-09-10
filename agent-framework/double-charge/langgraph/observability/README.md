# Observability and audit boundary

The app emits structured JSON logs correlated by case, run, node, transition,
checkpoint, retry attempt, and a one-way truncated idempotency-key hash. Install
`.[observability]` and set `APPLICATIONINSIGHTS_CONNECTION_STRING` to enable the
App Insights-ready OpenTelemetry setup in `infrastructure/telemetry.py`.

For Foundry Hosted Agents, the project-level `ApplicationInsights` connection is
created by this lane's Bicep and the Responses runtime injects the connection string.
The adapter creates a `foundry.responses.invoke` span, each graph command creates a
`workflow.run` span, and real executing nodes create `workflow.node.*` spans.
Actual deterministic tool awaits and model calls are children of the executing
node. Model spans record real token usage when supplied. No node/tool spans are
reconstructed from audit timestamps, and no artificial MAF agent layer is added.
Separate start, approval and resume requests retain their own operation IDs and
safe hashed case/run correlation.

This teaching deployment requires full native retention, configured and checked
after SDK initialization. Hosted SDK providers/exporters remain SDK-owned; API
bootstrap owns its providers and cleanup. The pinned hosted stack is tested
independently from MAF. Do not copy version-sensitive MAF fixes or infer live
instrumentor state from environment configuration alone.

API log export is attached only to the `model_to_harness_langgraph` logger
namespace, not the root logger: exporting Azure SDK transport/exporter logs can
recursively generate more export logs and prevent shutdown from draining.
Startup failures emit `runtime_startup_failed` with the exception class only,
before owned resources unwind; exception text and stacks remain excluded.

`trace-completeness.kql` checks one fresh no-duplicate operation, including exact
node set, workflow/model presence, parent linkage and sampling weight. Empty input
fails. Extend the executed-node expectation for other branches rather than
requiring every graph node in every operation. `trace-safety.kql` returns only
prohibited attribute key names, never unrestricted attributes. `command-traces.kql`
indexes actual commands, including failed and approval-only commands, without
promoting standalone SDK setup or log operations into workflow runs.

Resolve the exact project, version, App Insights resource and time window before
querying; display the KQL before execution and never claim aggregate counts prove
all individual traces complete. Local query files are acceptance tools, not proof
of deployed ingestion until a fresh operation passes them.

Durable business audit is different: ordered application-schema `events`, insert-once
approval commands, idempotent refund records and fingerprints, run projections,
outcomes, and selected memory remain in PostgreSQL.
The cutover application default is `langgraph_app_cutover`, with native checkpoint
tables in the separate `langgraph_checkpoints_cutover` schema.
They support resume but are not an audit API and are never returned to the browser.

Allowed telemetry: event names, latency, counts, route names, safe summaries, hashed
correlation values. Forbidden telemetry: raw prompts, complaint text, model
chain-of-thought, credentials, access tokens, unrestricted tool inputs/results, raw
checkpoint state, and database connection strings.
