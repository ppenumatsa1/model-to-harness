#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec .venv/bin/uvicorn maf_double_charge.api.app:create_app \
  --factory --reload --host 127.0.0.1 --port 8010
