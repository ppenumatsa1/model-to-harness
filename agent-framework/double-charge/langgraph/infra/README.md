# Independent Azure deployment

This directory is owned only by the LangGraph lane. It does not import deployment
modules, runtime code, identities, databases, images, or azd state from the MAF lane.

`main.bicep` targets an existing resource group and requires the resolved location.
The cutover release uses existing lane resources and references its existing
Foundry account/project/model rather than provisioning another. The template manages:

- ACR, Log Analytics, workspace-based Application Insights, and a Container Apps
  environment;
- an internal Python 3.12 FastAPI Container App and an external React/nginx
  Container App;
- PostgreSQL Flexible Server 16 with one lane-owned database;
- user-assigned Container App identities with only ACR pull and backend model-use
  roles, plus model-use access for the Foundry project identity.

The public frontend proxies `/api`, `/health`, and `/ready` to the internal backend.
The backend and hosted adapter use the same parameterized `langgraph_app_cutover`
audit schema and `langgraph_checkpoints_cutover` saver schema. PostgreSQL remains authoritative; no browser or
hosted-agent response receives checkpoint payloads, prompts, tool arguments, secrets,
or unrestricted workflow state.

## Deployment sources

- `container/Dockerfile` builds the Python 3.12 FastAPI image from the repository
  root so it can install this lane and the neutral shared package.
- `app/frontend.Dockerfile` builds the React app and serves it with the nginx
  same-origin proxy.
- `foundry-hosted/agent` is a direct-code Python 3.13 service. Run
  `python scripts/prepare_hosted.py` to deterministically copy this lane's package and
  `model_to_harness_shared` into its ignored `_packages/` directory and write a
  content-hash manifest before `azd deploy`.

## Parameters and secrets

Resource names, images, model deployment, database names, and the optional operator IP
are parameters. `postgresAdministratorPassword` is a secure Bicep parameter.
`scripts/deploy_azure.sh` reads existing values from the selected azd environment and
ARM, verifies agreement and refuses credential rotation. Secure Bicep parameters
are written only to private temporary files. Bicep emits no database URL or password
output. The hosted platform injects its monitoring connection string; do not
override its reserved environment variable.

## Ordered cutover

`scripts/deploy_azure.sh --environment langgraph` is read-only discovery and ARM
preview. `--apply` additionally requires committed source, immutable digest builds,
reviewed final what-if, explicit paired-schema setup, deployment and healthy
revision readback. Existing stopped PostgreSQL must be explicitly started first;
the script never changes its SKU or silently starts it. Fresh setup refuses either
schema already existing. `--update-existing` instead verifies the deployed pair
without DDL/reset.

Hosted deployment is separate: prepare the isolated source, set the same selected
schema pair in azd, deploy this lane's Responses service and verify its actual
version, archive and environment. `scripts/package_smoke.py` checks wheels outside
checkout; `--hosted` checks the hash-pinned Python 3.13 bundle and actual offline
Responses start/approval/resume using explicit doubles. Neither is a substitute for
cloud smoke, seven API/hosted scenarios, browser E2E, SQL/evaluation evidence and
per-operation trace gates after rollout.

The template enables public service endpoints and the PostgreSQL Azure-services
firewall rule for a compact educational deployment. Production deployments should
replace those defaults with private networking and explicitly approved egress.
