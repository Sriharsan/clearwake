#!/usr/bin/env sh
# One command run: starts Clearwake on http://127.0.0.1:8810 with a fresh database.
# Local by default (local provider, local records). Usage: ./run.sh [completed|pending|lost-response]
cd "$(dirname "$0")" || exit 1
OUTCOME="${1:-completed}"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
DB="data/local-$OUTCOME-$(date +%Y%m%d-%H%M%S)/case.sqlite3"
echo "LOCAL MODE. Local provider, local records. Open http://127.0.0.1:8810"
exec "$PY" -m clearwake --port 8810 --database "$DB" --local-outcome "$OUTCOME"
