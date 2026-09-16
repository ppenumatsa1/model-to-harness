#!/usr/bin/env bash
set -euo pipefail

LANE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$LANE_DIR"
BACKEND_PORT="${E2E_BACKEND_PORT:-18000}"
FRONTEND_PORT="${E2E_FRONTEND_PORT:-15173}"
export TELEMETRY_ENABLED=false
export FRONTEND_HOST=127.0.0.1 FRONTEND_PORT
export BACKEND_PROXY_URL="http://127.0.0.1:$BACKEND_PORT"
export UI_BASE_URL="http://127.0.0.1:$FRONTEND_PORT"

.venv/bin/python - "$BACKEND_PORT" "$FRONTEND_PORT" <<'PY'
import socket
import sys
from contextlib import ExitStack

with ExitStack() as stack:
    for value in sys.argv[1:]:
        port = int(value)
        if not 1 <= port <= 65535:
            raise SystemExit("E2E ports must be between 1 and 65535")
        server = stack.enter_context(socket.socket())
        server.bind(("127.0.0.1", port))
PY

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

export PYTHONPATH="$LANE_DIR/backend/src:$LANE_DIR/backend/tests:$LANE_DIR/../../../shared/src${PYTHONPATH:+:$PYTHONPATH}"
.venv/bin/uvicorn e2e_app:app --host 127.0.0.1 --port "$BACKEND_PORT" >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
(cd frontend && exec ./node_modules/.bin/vite --host 127.0.0.1) >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

for _ in {1..30}; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null || ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    break
  fi
  if curl --fail --silent "http://127.0.0.1:$BACKEND_PORT/ready" >/dev/null \
    && curl --fail --silent "$UI_BASE_URL" >/dev/null; then
    npm --prefix frontend run e2e
    exit 0
  fi
  sleep 1
done

cat "$BACKEND_LOG"
cat "$FRONTEND_LOG"
exit 1
