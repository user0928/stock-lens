#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Run sh setup.sh first"; exit 1; }
[ -f dist/index.html ] || { echo "Run npm run build first"; exit 1; }
exec .venv/bin/python -m uvicorn backend.app:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8765}"
