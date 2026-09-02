# Independent Azure deployment

This directory is owned only by the LangGraph lane. It does not import deployment
modules, runtime code, identities, databases, images, or azd state from the MAF lane.

`main.bicep` targets an existing resource group and defaults to `northcentralus`. It
creates:

- a system-assigned Microsoft Foundry account and project;
- a parameterized `gpt-5.6-sol` `2026-07-09` GlobalStandard deployment;
- ACR, Log Analytics, workspace-based Application Insights, and a Container Apps
  environment;
- an internal Python 3.12 FastAPI Container App and an external React/nginx
  Container App;
- PostgreSQL Flexible Server 16 with one lane-owned database;
- user-assigned Container App identities with only ACR pull and backend model-use
  roles, plus model-use access for the Foundry project identity.

The public frontend proxies `/api`, `/health`, and `/ready` to the internal backend.
The backend and hosted adapter use the same `langgraph_app` audit schema and
`langgraph_checkpoints` saver schema. PostgreSQL remains authoritative; no browser or
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

Resource names, images, model capacity, database names, and the optional operator IP
are parameters. `postgresAdministratorPassword` is a secure Bicep parameter.
`scripts/deploy_azure.sh` stores the generated/provided password, database URL, and
Application Insights connection string only in the selected azd environment and
injects them into Container Apps or the hosted agent. Bicep emits no database URL or
password output.

The template enables public service endpoints and the PostgreSQL Azure-services
firewall rule for a compact educational deployment. Production deployments should
replace those defaults with private networking and explicitly approved egress.
