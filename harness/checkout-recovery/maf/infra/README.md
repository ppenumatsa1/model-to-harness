# Checkout-recovery MAF infrastructure

`app/main.bicep` is lane-owned application foundation infrastructure. It creates an isolated ACR,
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
image digests or tags. Foundation preview is not approval to apply changes.

For an existing environment, `scripts/release.py` owns the guarded image-only
release path: save and approve the preview, pin immutable images, and verify both
apps' configuration and ready revisions before and after updates. Do not rerun
foundation provisioning for an application-code rollout. Foundry Hosted source
packaging and version selection remain separate lane-owned steps.

## Acceptance sequence

Keep the same evidence stages as the other independent MAF example, without
sharing release scripts or assuming identical business cases:

1. Local backend/frontend checks, dedicated local PostgreSQL restart/approval
   scenarios, offline evaluation and sanitized telemetry-parentage checks.
2. Later, explicitly approved Foundry packaging/deployment and guarded app-image
   rollout, with additive migrations applied explicitly where required.
3. Smoke, API and Hosted E2E, browser flow, native evaluations, then telemetry:
   record case/run identities and verify both Foundry correlation and App Insights
   ingestion, actual parent chains and content redaction.

Use separate evidence directories for each attempt. Preserve failed receipts,
existing database keys/checkpoints, resource identities and monitoring settings.
Local test success is not proof of cloud deployment or trace ingestion. The
current platform-pattern alignment is local-only; its cloud gates are deferred.
