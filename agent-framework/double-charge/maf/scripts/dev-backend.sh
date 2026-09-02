#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec .venv/bin/uvicorn maf_double_charge.main:app --reload --host 127.0.0.1 --port 8010

