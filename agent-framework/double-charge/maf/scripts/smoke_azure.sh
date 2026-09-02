#!/usr/bin/env bash
set -euo pipefail

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-model-harness}"
FRONTEND_URL="$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name model-harness-maf-app \
  --query properties.outputs.frontendUrl.value \
  -o tsv)"

curl -fsS "$FRONTEND_URL/api/scenarios" >/dev/null
curl -fsS "$FRONTEND_URL/api/workflow/graph" >/dev/null
curl -fsS "$FRONTEND_URL/health/ready" >/dev/null
printf 'MAF frontend and FastAPI proxy are ready: %s\n' "$FRONTEND_URL"
