#!/bin/bash
# Health check: one-shot for cron; interactive loop when run from a terminal.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source venv/bin/activate 2>/dev/null || true

_run_once() {
  python check_health.py
}

if [[ -t 1 ]] && [[ "${FORTRESS_CRON_ONCE:-}" != "1" ]]; then
  while true; do
    clear
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  🏥 TRADING BOT HEALTH MONITOR - Auto-refresh every 10 sec     ║"
    echo "║  $(date +'%Y-%m-%d %H:%M:%S %Z')                                          ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    _run_once 2>/dev/null || true
    echo ""
    echo "Press Ctrl+C to exit | Refreshing in 10 seconds..."
    sleep 10
  done
else
  _run_once
fi
