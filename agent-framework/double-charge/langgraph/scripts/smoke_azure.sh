#!/usr/bin/env bash
set -euo pipefail

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-model-harness}"
DEPLOYMENT_NAME="${AZURE_DEPLOYMENT_NAME:-model-harness-langgraph}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
FRONTEND_URL="${FRONTEND_URL:-$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --query properties.outputs.frontendUrl.value \
  -o tsv)}"

curl -fsS "$FRONTEND_URL/ready" >/dev/null
curl -fsS "$FRONTEND_URL/api/scenarios" >/dev/null

FRONTEND_URL="$FRONTEND_URL" "$PYTHON_BIN" - <<'PY'
import json
import os
import urllib.request


base = os.environ["FRONTEND_URL"]


def request(path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)


started = request(
    "/api/cases",
    {
        "complaint": "I was charged twice for the same purchase.",
        "customer_id": "azure-smoke",
        "scenario_id": "duplicate-confirmed",
    },
)
assert started["status"] == "paused", started
case_id = started["case_id"]
request(
    f"/api/cases/{case_id}/approval",
    {
        "checkpoint_id": started["checkpoint_id"],
        "decision": "approve",
        "reviewer_id": "azure-smoke",
        "reason": "Deployment smoke test",
    },
)
resumed = request(f"/api/cases/{case_id}/resume", {})
assert resumed["status"] in {"completed", "manual_review"}, resumed
print(f"FastAPI durable command smoke passed for {case_id}")
PY

if [[ "${SMOKE_HOSTED_AGENT:-0}" == "1" ]]; then
  AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent invoke \
    --new-session \
    --new-conversation \
    '{"action":"start","scenario_id":"no-duplicate","complaint":"I may have been charged twice.","customer_id":"hosted-smoke"}'
fi

printf 'LangGraph frontend and same-origin API proxy are ready: %s\n' "$FRONTEND_URL"
