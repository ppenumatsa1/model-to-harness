# Observability and durable audit

The app deliberately keeps two evidence planes separate:

1. **Durable business audit** in the app-owned PostgreSQL schema: run state, MAF
   checkpoints, approvals, ordered execution events, selected memory, and normalized
   outcomes. These records support recovery, replay, evaluation, and operator review.
2. **Operational telemetry**: structured JSON logs and OpenTelemetry spans for
   latency, availability, retries, and correlation. Telemetry may be sampled or
   expire; it is not the business source of truth.

Every structured log can carry `case_id`, `run_id`, `node`, `transition`,
`checkpoint_id`, `retry_attempt`, and `idempotency_key`. Event payloads are
allowlisted and never contain raw prompts, credentials, checkpoint bodies, or
chain-of-thought.

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to enable OTLP/HTTP trace export. An
`APPLICATIONINSIGHTS_CONNECTION_STRING` placeholder is included for future Azure
Monitor distribution setup, but v1 does not silently install or enable an exporter.
Do not commit real connection strings.

Useful operator queries are in `queries.sql`.

