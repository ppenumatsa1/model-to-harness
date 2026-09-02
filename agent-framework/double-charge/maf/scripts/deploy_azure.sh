#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
LANE_DIR="$ROOT_DIR/agent-framework/double-charge/maf"
SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:-7df95e88-701c-4693-af77-3159f83b558d}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-model-harness}"
LOCATION="${AZURE_LOCATION:-northcentralus}"
DEPLOYMENT_NAME="model-harness-maf-app"
AZURE_ENV_NAME="${AZURE_ENV_NAME:-maf-dev}"
POSTGRES_PASSWORD="${POSTGRES_ADMIN_PASSWORD:-}"
RELEASE_TAG="${RELEASE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$LANE_DIR"

az account set --subscription "$SUBSCRIPTION_ID"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env select "$AZURE_ENV_NAME" >/dev/null
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_SUBSCRIPTION_ID "$SUBSCRIPTION_ID"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_LOCATION "$LOCATION"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_AI_DEPLOYMENTS_LOCATION "$LOCATION"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_RESOURCE_GROUP "$RESOURCE_GROUP"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_AI_PROJECT_NAME model-harness-maf
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME model-harness-gpt-5-6-sol
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd provision --no-prompt

eval "$(AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env get-values)"
PROJECT_ID="${AZURE_AI_PROJECT_ID:?AZURE_AI_PROJECT_ID was not produced by azd provision}"
PROJECT_ENDPOINT="${FOUNDRY_PROJECT_ENDPOINT:?FOUNDRY_PROJECT_ENDPOINT was not produced}"
FOUNDRY_ACCOUNT_NAME="$(printf '%s' "$PROJECT_ID" | sed -E 's#^.*/accounts/([^/]+)/projects/.*#\1#')"
FOUNDRY_PROJECT_NAME="$(printf '%s' "$PROJECT_ID" | sed -E 's#^.*/projects/([^/]+)$#\1#')"
OPERATOR_IP="$(curl -fsS https://api.ipify.org)"
if [[ -z "$POSTGRES_PASSWORD" ]]; then
  if EXISTING_POSTGRES_PASSWORD="$(
    AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
      azd env get-value POSTGRES_ADMIN_PASSWORD 2>/dev/null
  )"; then
    POSTGRES_PASSWORD="$EXISTING_POSTGRES_PASSWORD"
  fi
fi
if [[ -z "$POSTGRES_PASSWORD" ]]; then
  POSTGRES_PASSWORD="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set \
  POSTGRES_ADMIN_PASSWORD "$POSTGRES_PASSWORD" >/dev/null

az deployment group create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME-bootstrap" \
  --template-file infra/app/main.bicep \
  --parameters \
    location="$LOCATION" \
    foundryAccountName="$FOUNDRY_ACCOUNT_NAME" \
    foundryProjectName="$FOUNDRY_PROJECT_NAME" \
    foundryProjectEndpoint="$PROJECT_ENDPOINT" \
    modelDeploymentName=model-harness-gpt-5-6-sol \
    postgresAdministratorPassword="$POSTGRES_PASSWORD" \
    operatorIp="$OPERATOR_IP" \
  --only-show-errors

REGISTRY_NAME="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME-bootstrap" --query properties.outputs.registryName.value -o tsv)"
REGISTRY_SERVER="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME-bootstrap" --query properties.outputs.registryLoginServer.value -o tsv)"
POSTGRES_HOST="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME-bootstrap" --query properties.outputs.postgresHost.value -o tsv)"
DATABASE_URL="postgresql://mthadmin:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:5432/model_harness_maf?sslmode=require"

az acr build \
  --registry "$REGISTRY_NAME" \
  --image "model-harness-maf-backend:$RELEASE_TAG" \
  --file "$LANE_DIR/infra/container/Dockerfile" \
  "$ROOT_DIR" \
  --no-logs
az acr build \
  --registry "$REGISTRY_NAME" \
  --image "model-harness-maf-frontend:$RELEASE_TAG" \
  --file "$LANE_DIR/infra/app/frontend.Dockerfile" \
  "$ROOT_DIR" \
  --no-logs

az deployment group create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --template-file infra/app/main.bicep \
  --parameters \
    location="$LOCATION" \
    foundryAccountName="$FOUNDRY_ACCOUNT_NAME" \
    foundryProjectName="$FOUNDRY_PROJECT_NAME" \
    foundryProjectEndpoint="$PROJECT_ENDPOINT" \
    modelDeploymentName=model-harness-gpt-5-6-sol \
    postgresAdministratorPassword="$POSTGRES_PASSWORD" \
    operatorIp="$OPERATOR_IP" \
    backendImage="$REGISTRY_SERVER/model-harness-maf-backend:$RELEASE_TAG" \
    backendTargetPort=8010 \
    frontendImage="$REGISTRY_SERVER/model-harness-maf-frontend:$RELEASE_TAG" \
  --only-show-errors

AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set DATABASE_URL "$DATABASE_URL"
"$PYTHON_BIN" scripts/prepare_hosted.py
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy model-harness-maf --no-prompt

AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent show --output json
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent invoke \
  model-harness-maf --new-session --new-conversation \
  '{"action":"start","scenario_id":"no-duplicate","complaint":"I may have been charged twice.","customer_id":"azure-smoke"}'

az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --query properties.outputs.frontendUrl.value \
  -o tsv
