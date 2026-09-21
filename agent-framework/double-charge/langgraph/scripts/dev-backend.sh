#!/usr/bin/env bash
set -euo pipefail

lane_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$lane_root"
export PYTHONPATH="$lane_root/backend/src:$lane_root/../../../shared/src${PYTHONPATH:+:$PYTHONPATH}"
python="$lane_root/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  echo "Missing LangGraph .venv/bin/python; install the lane's development environment first." >&2
  exit 1
fi
exec "$python" -m model_to_harness_langgraph.main
