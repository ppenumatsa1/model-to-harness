#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${1:-}" == "--base-url" ]]; then
  export MAF_UI_URL="${2:?--base-url requires the deployed same-origin frontend URL}"
  shift 2
elif [[ "${1:-}" != "" ]]; then
  printf 'Usage: %s [--base-url https://deployed-frontend]\n' "$0" >&2
  exit 2
fi
if [[ -n "${MAF_UI_URL:-}" ]]; then
  curl -fsS "${MAF_UI_URL%/}/health/ready" >/dev/null
  exec npm --prefix frontend run e2e -- "$@"
fi

.venv/bin/uvicorn maf_double_charge.testing.app:create_test_app \
  --factory --host 127.0.0.1 --port 8010 > .e2e-backend.log 2>&1 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true; rm -f .e2e-backend.log' EXIT

for _ in $(seq 1 30); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    printf 'Local test API exited before readiness; check for a port conflict.\n' >&2
    exit 1
  fi
  if curl -fsS http://127.0.0.1:8010/health/live >/dev/null 2>&1; then
    npm --prefix frontend run e2e
    exit 0
  fi
  sleep 1
done

printf 'Local test API did not become ready; backend log suppressed.\n' >&2
exit 1
