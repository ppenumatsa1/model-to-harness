#!/usr/bin/env bash
set -euo pipefail

LANE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${FRONTEND_URL:?Set the verified LangGraph frontend URL}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" "$LANE_DIR/scripts/api_harness.py" --base-url "$FRONTEND_URL" --smoke

if [[ "${SMOKE_HOSTED_AGENT:-0}" == "1" ]]; then
  : "${HOSTED_AGENT_VERSION:?Set the verified immutable hosted version}"
  : "${HOSTED_TRANSPORT:?Select azd or sdk explicitly}"
  "$PYTHON_BIN" "$LANE_DIR/scripts/hosted_harness.py" \
    --environment "${AZURE_ENV_NAME:-langgraph}" --version "$HOSTED_AGENT_VERSION" \
    --transport "$HOSTED_TRANSPORT" --smoke
fi
