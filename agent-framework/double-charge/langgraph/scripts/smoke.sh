#!/usr/bin/env bash
set -euo pipefail

LANE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${PYTHON_BIN:-python3}" "$LANE_DIR/scripts/api_harness.py" \
  --base-url "${API_BASE_URL:-http://127.0.0.1:8000}" --smoke
