#!/usr/bin/env sh
# Shell equivalent of scripts/sandbox_setup.ps1
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" scripts/sandbox_setup.py "$@"
