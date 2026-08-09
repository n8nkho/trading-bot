#!/bin/bash
# Live monitor: one-shot for cron; interactive loop when run from a terminal.
set -euo pipefail
cd "$(dirname "$0")"

_run_once() {
  echo "╔════════════════════════════════════════════════════════════╗"
  echo "║         TRADING BOT LIVE MONITOR                          ║"
  echo "╚════════════════════════════════════════════════════════════╝"
  echo ""
  echo "⏰ $(date)"
  echo ""
  hour=$(date +%H)
  if [ "$hour" -ge 9 ] && [ "$hour" -lt 16 ]; then
    echo "📊 Market: OPEN"
  else
    echo "💤 Market: CLOSED"
  fi
  echo ""
  echo "🔧 PROCESSES:"
  pgrep -f dashboard >/dev/null && echo "  ✅ Dashboard" || echo "  ❌ Dashboard"
  echo "  ✅ LLM: DeepSeek (no local Ollama)"
  echo ""
  echo "📜 RECENT ACTIVITY:"
  tail -5 logs/sniper.log 2>/dev/null | sed 's/^/  /' || true
  echo ""
  echo "💼 POSITIONS:"
  if [ -f data/positions.json ]; then
    python3 -c "import json; p=json.load(open('data/positions.json')); print(f'  Open: {len(p)}') if p else print('  None')" 2>/dev/null || echo "  (read error)"
  else
    echo "  None"
  fi
  echo ""
}

if [[ -t 1 ]] && [[ "${FORTRESS_CRON_ONCE:-}" != "1" ]]; then
  while true; do
    clear
    _run_once
    echo "Press Ctrl+C to exit"
    sleep 5
  done
else
  _run_once
fi
