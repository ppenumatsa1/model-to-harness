#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "${1:-}" == "--base-url" ]]; then
  export MAF_BASE_URL="${2:?--base-url requires the deployed same-origin frontend URL}"
  shift 2
fi
: "${MAF_BASE_URL:?Set MAF_BASE_URL or pass --base-url; never infer another Azure target}"
exec "${PYTHON_BIN:-.venv/bin/python}" scripts/smoke.py --base-url "$MAF_BASE_URL" "$@"
