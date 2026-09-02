#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-}:backend/src:../../../shared/src"
exec uvicorn model_to_harness_langgraph.main:app --reload --host 127.0.0.1 --port 8000

