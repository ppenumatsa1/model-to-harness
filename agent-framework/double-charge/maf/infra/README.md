# Infrastructure placeholder

This folder intentionally contains no live subscription, resource name, secret, or
deployment claim. A future deployment should independently provision or bind:

- A Python 3.12 container/web host for this FastAPI app.
- A static/web host for `frontend/dist`.
- A PostgreSQL database exposed through `DATABASE_URL`; this app owns only the
  `maf_double_charge` schema and migration lifecycle.
- Managed identity with least-privilege access to the selected Microsoft Foundry
  project/model.
- Secret injection for database and telemetry configuration.
- Private networking, health probes, scaling, backup, and retention appropriate to
  the target environment.

Do not reuse deployment modules from the LangGraph app. Add Bicep or Terraform here
only after concrete resource, region, identity, and networking decisions are
approved.

The placeholder backend Dockerfile expects the repository root as its build context:

```bash
docker build -f agent-framework/double-charge/maf/infra/container/Dockerfile .
```
