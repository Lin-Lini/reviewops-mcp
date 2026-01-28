#!/usr/bin/env bash
set -euo pipefail

curl -fsS http://localhost:8000/health >/dev/null
curl -fsS http://localhost:9000/health >/dev/null
python scripts/smoke.py