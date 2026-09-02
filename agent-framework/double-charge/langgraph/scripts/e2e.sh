#!/usr/bin/env bash
set -euo pipefail

python3 -m pytest backend/tests
npm --prefix frontend test
npm --prefix frontend run build

