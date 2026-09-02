#!/usr/bin/env bash
set -euo pipefail

BACKEND_LOG=.e2e-backend.log
FRONTEND_LOG=.e2e-frontend.log
BACKEND_PID=
FRONTEND_PID=

cleanup() {
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  rm -f "$BACKEND_LOG" "$FRONTEND_LOG"
}
trap cleanup EXIT

export PYTHONPATH="${PYTHONPATH:-}:backend/src:backend/tests:../../../shared/src"
.venv/bin/uvicorn e2e_app:app --host 127.0.0.1 --port 8000 >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
(cd frontend && exec ./node_modules/.bin/vite --host 127.0.0.1) >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

for _ in {1..30}; do
  if curl --fail --silent http://127.0.0.1:8000/ready >/dev/null \
    && curl --fail --silent http://127.0.0.1:5173 >/dev/null; then
    npm --prefix frontend run e2e
    exit 0
  fi
  sleep 1
done

cat "$BACKEND_LOG"
cat "$FRONTEND_LOG"
exit 1
