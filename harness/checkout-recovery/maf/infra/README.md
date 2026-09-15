# Checkout-recovery MAF infrastructure

`main.bicep` is lane-owned foundation infrastructure. It creates an isolated ACR,
PostgreSQL Flexible Server/database, Log Analytics/App Insights, Container Apps
environment, private FastAPI Container App, public React/nginx Container App, and
separate user-assigned pull identities. Image references, operator IP, Foundry
endpoint, model deployment, and database credentials are deployment parameters.
No endpoint, subscription, identifier, password, or connection string is stored
in this directory.

The `azure.yaml` project provisions the isolated Foundry project, model deployment,
and Hosted Agent separately using `azd`; do not use its generated values until the
selected environment has been reviewed. Before a Bicep deployment, resolve the
actual Foundry project endpoint and model deployment from that environment and pass
them as parameters. The Bicep foundation never runs migrations or deploys agent code.

Preview only:

```bash
scripts/preview_deploy.sh --resource-group <resource-group> --parameters <secure-parameters.json>
```

The parameter file must supply `backendImage`, `frontendImage`,
`foundryProjectEndpoint`, `foundryModelDeployment`, and
`postgresAdministratorPassword`; it must remain outside source control. Use immutable
image digests or tags. Apply is intentionally not automated by this lane.
