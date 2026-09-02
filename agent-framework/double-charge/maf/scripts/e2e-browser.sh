#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

.venv/bin/uvicorn maf_double_charge.api:create_test_app \
  --factory --host 127.0.0.1 --port 8010 > .e2e-backend.log 2>&1 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true; rm -f .e2e-backend.log' EXIT

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8010/health/live >/dev/null 2>&1; then
    npm --prefix frontend run e2e
    exit 0
  fi
  sleep 1
done

cat .e2e-backend.log
exit 1
