#!/bin/bash
# Live auto-refreshing health dashboard

while true; do
    clear
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  🏥 TRADING BOT HEALTH MONITOR - Auto-refresh every 10 sec     ║"
    echo "║  $(date +'%Y-%m-%d %H:%M:%S %Z')                                          ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    
    cd ~/trading-bot
    source venv/bin/activate 2>/dev/null
    python check_health.py 2>/dev/null
    
    echo ""
    echo "Press Ctrl+C to exit | Refreshing in 10 seconds..."
    sleep 10
done
