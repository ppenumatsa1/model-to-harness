# Technology stack

- Python 3.13, Microsoft Agent Framework Harness Agent, FastAPI, Uvicorn,
  Pydantic v2, and Psycopg 3.
- PostgreSQL for application state, approvals, remediation ledger, evidence, and
  audit records.
- Azure Identity and Foundry model integration; Foundry Hosted Agents run the
  separately packaged Responses 2.0 adapter.
- React, TypeScript, Vite, Vitest, and Playwright for the independent UI.
- OpenTelemetry and Application Insights for safe operational telemetry.
- Bicep, azd, ACR, Container Apps, a lane-owned Foundry project/agent, managed
  identity, and lane-owned telemetry resources for deployment.

The Hosted Agent is the runtime. The MAF Harness Agent is the harness.
