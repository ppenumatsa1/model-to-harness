#!/usr/bin/env bash
set -euo pipefail

LANE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$LANE_DIR"
# No azd environment edits, account selection, implicit provisioning or transport fallback.
exec "${PYTHON_BIN:-python3}" scripts/release.py "$@"
