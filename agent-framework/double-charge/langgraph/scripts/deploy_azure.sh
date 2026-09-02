#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
LANE_DIR="$ROOT_DIR/agent-framework/double-charge/langgraph"
SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-model-harness}"
LOCATION="${AZURE_LOCATION:-northcentralus}"
AZURE_ENV_NAME="${AZURE_ENV_NAME:-langgraph}"
DEPLOYMENT_NAME="${AZURE_DEPLOYMENT_NAME:-model-harness-langgraph}"
MODEL_CAPACITY="${AZURE_AI_MODEL_CAPACITY:-100}"
POSTGRES_LOGIN="${POSTGRES_ADMINISTRATOR_LOGIN:-mthadmin}"
POSTGRES_PASSWORD="${POSTGRES_ADMINISTRATOR_PASSWORD:-}"
OPERATOR_IP="${OPERATOR_IP:-}"
FOUNDRY_ACCOUNT_NAME="${AZURE_AI_ACCOUNT_NAME:-}"
RELEASE_TAG="${RELEASE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

for command in az azd curl "$PYTHON_BIN"; do
  command -v "$command" >/dev/null || {
    printf 'Required command not found: %s\n' "$command" >&2
    exit 1
  }
done

cd "$LANE_DIR"
az account set --subscription "$SUBSCRIPTION_ID"
az group show --name "$RESOURCE_GROUP" --output none

if ! AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env select "$AZURE_ENV_NAME" >/dev/null 2>&1; then
  AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env new "$AZURE_ENV_NAME" --no-prompt
fi

if [[ -z "$POSTGRES_PASSWORD" ]]; then
  if EXISTING_POSTGRES_PASSWORD="$(
    AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
      azd env get-value POSTGRES_ADMINISTRATOR_PASSWORD 2>/dev/null
  )"; then
    POSTGRES_PASSWORD="$EXISTING_POSTGRES_PASSWORD"
  fi
fi
if [[ -z "$POSTGRES_PASSWORD" ]]; then
  POSTGRES_PASSWORD="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(24))')"
fi

AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_SUBSCRIPTION_ID "$SUBSCRIPTION_ID"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_RESOURCE_GROUP "$RESOURCE_GROUP"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_LOCATION "$LOCATION"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set POSTGRES_ADMINISTRATOR_PASSWORD "$POSTGRES_PASSWORD"

BICEP_PARAMETERS=(
  location="$LOCATION"
  modelCapacity="$MODEL_CAPACITY"
  postgresAdministratorLogin="$POSTGRES_LOGIN"
  postgresAdministratorPassword="$POSTGRES_PASSWORD"
  operatorIp="$OPERATOR_IP"
)
if [[ -n "$FOUNDRY_ACCOUNT_NAME" ]]; then
  BICEP_PARAMETERS+=(foundryAccountName="$FOUNDRY_ACCOUNT_NAME")
fi

az deployment group create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --template-file infra/main.bicep \
  --parameters "${BICEP_PARAMETERS[@]}" \
  --only-show-errors

REGISTRY_NAME="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME" --query properties.outputs.registryName.value -o tsv)"
REGISTRY_SERVER="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME" --query properties.outputs.registryEndpoint.value -o tsv)"
POSTGRES_HOST="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME" --query properties.outputs.postgresHost.value -o tsv)"
POSTGRES_DATABASE="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME" --query properties.outputs.postgresDatabaseName.value -o tsv)"
PROJECT_ID="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME" --query properties.outputs.foundryProjectId.value -o tsv)"
PROJECT_ENDPOINT="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME" --query properties.outputs.foundryProjectEndpoint.value -o tsv)"
OPENAI_ENDPOINT="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME" --query properties.outputs.openAiEndpoint.value -o tsv)"
MODEL_DEPLOYMENT="$(az deployment group show -g "$RESOURCE_GROUP" -n "$DEPLOYMENT_NAME" --query properties.outputs.modelDeploymentName.value -o tsv)"
DATABASE_URL="postgresql://${POSTGRES_LOGIN}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:5432/${POSTGRES_DATABASE}?sslmode=require"

az acr build \
  --registry "$REGISTRY_NAME" \
  --image "model-harness-langgraph-backend:$RELEASE_TAG" \
  --file "$LANE_DIR/infra/container/Dockerfile" \
  "$ROOT_DIR" \
  --no-logs
az acr build \
  --registry "$REGISTRY_NAME" \
  --image "model-harness-langgraph-frontend:$RELEASE_TAG" \
  --file "$LANE_DIR/infra/app/frontend.Dockerfile" \
  "$ROOT_DIR" \
  --no-logs

az deployment group create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --template-file infra/main.bicep \
  --parameters \
    "${BICEP_PARAMETERS[@]}" \
    backendImage="$REGISTRY_SERVER/model-harness-langgraph-backend:$RELEASE_TAG" \
    backendTargetPort=8000 \
    frontendImage="$REGISTRY_SERVER/model-harness-langgraph-frontend:$RELEASE_TAG" \
    enableBackendProbes=true \
  --only-show-errors

AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_AI_PROJECT_ID "$PROJECT_ID"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_AI_PROJECT_ENDPOINT "$PROJECT_ENDPOINT"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set FOUNDRY_PROJECT_ENDPOINT "$PROJECT_ENDPOINT"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_OPENAI_ENDPOINT "$OPENAI_ENDPOINT"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME "$MODEL_DEPLOYMENT"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set DATABASE_URL "$DATABASE_URL"

"$PYTHON_BIN" scripts/prepare_hosted.py
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy model-harness-langgraph --no-prompt
AGENT_IDENTITIES_JSON="$(
  AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent show --output json
)"
AGENT_INSTANCE_PRINCIPAL_ID="$(
  printf '%s' "$AGENT_IDENTITIES_JSON" |
    "$PYTHON_BIN" -c 'import json, sys; print(json.load(sys.stdin)["instance_identity"]["principal_id"])'
)"
FOUNDRY_ACCOUNT_ID="${PROJECT_ID%/projects/*}"
az role assignment create \
  --assignee-object-id "$AGENT_INSTANCE_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" \
  --scope "$FOUNDRY_ACCOUNT_ID" \
  --only-show-errors \
  --output none

az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --query properties.outputs.frontendUrl.value \
  -o tsv
