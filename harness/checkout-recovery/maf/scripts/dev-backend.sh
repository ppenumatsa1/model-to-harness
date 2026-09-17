#!/usr/bin/env bash
set -euo pipefail
lane="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$lane"
exec "$lane/.venv/bin/python" -m checkout_recovery_maf
