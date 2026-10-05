#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3.11+ is required"; exit 1; }
command -v npm >/dev/null || { echo "Node.js 20.19+ is required"; exit 1; }
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements-lock.txt
npm ci
npm run build
echo "Setup complete. Run sh start.sh"
