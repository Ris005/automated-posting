#!/usr/bin/env bash
# One-command setup + run (macOS / Linux)
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements-dev.txt
fi
[ -f .env ] || cp .env.example .env
echo "Swagger UI -> http://localhost:4000/docs"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 4000
