#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCE_GROUP=""
PARAMETERS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group)
      RESOURCE_GROUP="${2:?--resource-group requires a value}"
      shift 2
      ;;
    --parameters)
      PARAMETERS="${2:?--parameters requires a value}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

[[ -n "$RESOURCE_GROUP" ]] || { echo "--resource-group is required" >&2; exit 2; }
[[ -n "$PARAMETERS" ]] || { echo "--parameters is required" >&2; exit 2; }
[[ -f "$PARAMETERS" ]] || { echo "Parameter file not found" >&2; exit 2; }

echo "Previewing Bicep changes only; no resources, migrations, images, or agents will be deployed."
az deployment group what-if \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$ROOT/infra/app/main.bicep" \
  --parameters "@$PARAMETERS" \
  --result-format ResourceIdOnly
