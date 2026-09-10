# Telemetry configuration and release verification

## API

1. Keep durable PostgreSQL auditing enabled regardless of telemetry export.
2. Select **one** export target:
   - Set `APPLICATIONINSIGHTS_CONNECTION_STRING` through the API platform secret
     store. The declared `azure-monitor-opentelemetry` dependency now enables actual
     Azure Monitor export when explicit application bootstrap runs.
   - Or set `OTEL_EXPORTER_OTLP_ENDPOINT` to an OTLP/HTTP collector base URL such as
     `http://localhost:4318`. The original `/v1/traces` endpoint form is accepted;
     sibling `/v1/logs` and `/v1/metrics` endpoints are derived. Credential-bearing
     URLs, queries, fragments and non-HTTP(S) schemes are rejected.
   - Unset both for local-disabled mode. No exporter/provider is constructed.
3. Set `OTEL_SERVICE_NAME` to the deployed API role and `OTEL_SERVICE_VERSION` to
   the actual build/release identifier. Defaults are `model-to-harness-maf-api`
   and the installed package version; defaults are not proof of a new release.
   An enabled destination combined with `OTEL_SDK_DISABLED=true` or a signal's
   `OTEL_*_EXPORTER=none` is a configuration error, not successful export.
4. Call `instrument_api_app(app, settings)` during the specific FastAPI app's
   construction, not lifespan startup. It uses proxy providers and creates no
   exporter. Runtime startup can then call `configure_telemetry(settings)` once per
   process in lifespan; call the returned handle's synchronous `shutdown()` from
   lifecycle cleanup.

The distro's default blanket instrumentations are explicitly disabled. Scoped
FastAPI request instrumentation and native MAF instrumentation are sufficient; do
not turn on request/response body capture, message events, tool payloads or
`ENABLE_SENSITIVE_DATA`. Logging uses fixed event names, not raw business summaries.
Use a collector and platform secret mechanism for ingestion authentication; never
put connection strings in source, log messages or browser configuration.

## Hosted Responses runtime

The hosted platform initializes its provider/exporter. Application bootstrap uses
`host="hosted"` after that initialization, registers pre-export safety without
replacing the provider, and never flushes/shuts down the platform's providers.
Do not call `configure_azure_monitor`, `set_tracer_provider`, or MAF provider-setup
helpers on this path. Do not inject the reserved App Insights connection-string
environment variable into hosted `azure.yaml`. Preserve platform role and version
identity; do not substitute an API role on hosted spans.

Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` in the hosted
environment **before** the Responses SDK initializes. Its content-capture setting
is separate from MAF's `enable_sensitive_data=False`; the latter alone does not
disable platform message capture. The release adapter owns this platform setting.
Do not depend on application log filtering to sanitize direct platform OTel events.

Hosted command context should use supplied conversation/response IDs together with
resolved case/run IDs. A resume is a new request/trace, not a continuation of a
blocked in-process approval wait.

## Local evidence

From this lane:

```bash
uv run --extra dev pytest backend/tests/unit/test_telemetry.py
```

These in-memory tests cover native MAF graph hierarchy, pre-existing exporter
ordering, unsafe attributes/events/exceptions/logs, separate-request correlation,
role preservation, no fabricated token usage, duplicate configuration, and owned
flush/shutdown. They do not establish Azure ingestion health.

## Deployed release gate

1. Resolve the existing deployment's linked App Insights resource and **actual**
   hosted role identity from deployment output and the narrow release window.
2. Record release start/end UTC, actual API build version and hosted agent version,
   plus safe case/run/conversation join keys from release exercises.
3. Adapt `release-verification.kql` parameters. First select hosted requests by exact
   identity/time; then join dependencies/logs/exceptions by `operation_Id`. Do not
   filter every downstream span to an assumed role or mistake unrelated traffic for
   this release.
4. Verify native workflow/executor/edge/model/message relationships by parent ID
   and links, actual statuses/durations, and case/run joins across start, approval
   and resume. The template projects token values as nullable; missing stays missing.
5. Run the sensitive-*key* check without projecting suspect values. If it finds
   prohibited fields, fail the release gate and investigate using access-controlled
   tooling; do not paste raw telemetry contents into build artifacts.
6. Allow for configured sampling/ingestion delay and document that evidence limit.
   Missing records are not positive verification. Keep telemetry retention/sampling
   separate from SQL audit retention.

This document and the templates do not claim that a deployment was queried or
verified. The release operator must execute the bounded gate against the actual
linked resource.

## References

- [Azure Monitor Python configuration API](https://learn.microsoft.com/python/api/azure-monitor-opentelemetry/azure.monitor.opentelemetry)
- [Scoped logging and enabling the distro](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-enable)
- [Telemetry filtering](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-filter)
- [Native MAF observability and sensitive-data controls](https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/observability/README.md)
