# Optional telemetry setup

1. Keep durable audit storage enabled regardless of telemetry export.
2. Set `OTEL_EXPORTER_OTLP_ENDPOINT` for a standards-compatible OTLP/HTTP collector.
3. For Application Insights, install and configure the Azure Monitor
   OpenTelemetry distribution in a deployment-specific dependency layer, then inject
   `APPLICATIONINSIGHTS_CONNECTION_STRING` through the platform secret store.
4. Verify that exported attributes contain correlation IDs and safe summaries only.
5. Set retention and sampling independently from PostgreSQL audit retention.

The local v1 intentionally does not auto-enable an Azure exporter merely because a
connection string exists. This avoids a misleading production-observability claim
and keeps the Foundry/App Insights integration an explicit deployment decision.

