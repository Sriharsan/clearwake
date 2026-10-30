#!/usr/bin/env sh
# Shell equivalent of scripts/check_demo.ps1
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" scripts/check_demo.py "$@"
