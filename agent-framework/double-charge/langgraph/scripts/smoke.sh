#!/usr/bin/env bash
set -euo pipefail

: "${API_BASE_URL:=http://127.0.0.1:8000}"

curl --fail --silent --show-error "$API_BASE_URL/ready"
response="$(
  curl --fail --silent --show-error \
    -H "Content-Type: application/json" \
    -d '{"complaint":"I was charged twice for the same purchase.","customer_id":"smoke-customer","scenario_id":"duplicate-confirmed"}' \
    "$API_BASE_URL/api/cases"
)"
python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"] in {"paused","completed"}; print(json.dumps(value, indent=2))' <<<"$response"
