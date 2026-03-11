#!/bin/bash
# Refresh all recommendation sources and restart Command Center so the panel shows
# opportunity + hedging + defensive recommendations (6+ items).
set -e
cd "$(dirname "$0")/.."
echo "Refreshing recommendation data..."
venv/bin/python agents/opportunity_analyzer.py
venv/bin/python agents/hedging_opportunity_analyzer.py
venv/bin/python agents/defensive_universe_scanner.py
venv/bin/python agents/regime_alignment.py
venv/bin/python agents/no_trade_analyzer.py
venv/bin/python agents/pattern_miner.py
echo "Stopping existing Command Center (if any)..."
pkill -f "dashboard/command_center.py" 2>/dev/null || true
sleep 2
echo "Starting Command Center..."
nohup venv/bin/python dashboard/command_center.py >> logs/command_center.log 2>&1 &
sleep 3
echo "Done. Open Command Center and hard-refresh (Ctrl+Shift+R or Cmd+Shift+R) to see all recommendations."
