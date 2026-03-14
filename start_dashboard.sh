#!/usr/bin/env bash
# Start the Fortress dashboard. Leave this window open.
# After running setup.sh once, run this and open http://localhost:8083 in your browser.

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ -d "venv" ]; then
  source venv/bin/activate
fi

PORT="${COMMAND_CENTER_PORT:-8083}"
echo ""
echo "  Fortress Command Center starting..."
echo "  Open in your browser: http://localhost:${PORT}"
echo "  (Leave this window open.)"
echo ""
python3 dashboard/command_center.py
