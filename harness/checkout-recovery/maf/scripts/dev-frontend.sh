#!/usr/bin/env bash
set -euo pipefail
lane="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$lane/frontend"
exec npm run dev -- "$@"
