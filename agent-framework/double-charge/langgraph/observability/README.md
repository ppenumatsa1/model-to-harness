# Observability and audit boundary

The app emits structured JSON logs correlated by case, run, node, transition,
checkpoint, retry attempt, and a one-way truncated idempotency-key hash. Install
`.[observability]` and set `APPLICATIONINSIGHTS_CONNECTION_STRING` to enable the
App Insights-ready OpenTelemetry setup in `observability.py`.

Operational telemetry may be sampled and retained according to platform policy.
Durable business audit is different: ordered `langgraph_app.events`, insert-once
approval commands, idempotent refund records and fingerprints, run projections,
outcomes, and selected memory remain in PostgreSQL.
LangGraph checkpoint tables live in the separate `langgraph_checkpoints` schema.
They support resume but are not an audit API and are never returned to the browser.

Allowed telemetry: event names, latency, counts, route names, safe summaries, hashed
correlation values. Forbidden telemetry: raw prompts, complaint text, model
chain-of-thought, credentials, access tokens, unrestricted tool inputs/results, raw
checkpoint state, and database connection strings.
