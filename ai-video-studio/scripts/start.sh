#!/usr/bin/env bash
# AI Video Studio launcher for Linux/macOS (e.g. a homelab box).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt
  cp requirements.txt .venv/installed-requirements.txt
fi
if [ ! -f app/frontend/dist/index.html ]; then
  (cd app/frontend && npm ci --no-audit --no-fund && npm run build)
fi
command -v ffmpeg >/dev/null || echo "Note: FFmpeg not found; assembly will not work until it is installed."
PYTHONPATH="$ROOT/app/backend" exec .venv/bin/python -m studio
