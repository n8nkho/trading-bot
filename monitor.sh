#!/bin/bash
# Real-time monitoring dashboard

while true; do
    clear
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║         TRADING BOT LIVE MONITOR                          ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    
    # Time
    echo "⏰ $(date)"
    echo ""
    
    # Market status
    hour=$(date +%H)
    if [ $hour -ge 9 ] && [ $hour -lt 16 ]; then
        echo "📊 Market: OPEN"
    else
        echo "💤 Market: CLOSED"
    fi
    echo ""
    
    # Processes
    echo "🔧 PROCESSES:"
    pgrep -f dashboard > /dev/null && echo "  ✅ Dashboard" || echo "  ❌ Dashboard"
    systemctl is-active --quiet ollama && echo "  ✅ Ollama" || echo "  ❌ Ollama"
    echo ""
    
    # Recent logs
    echo "📜 RECENT ACTIVITY:"
    tail -5 logs/sniper.log 2>/dev/null | sed 's/^/  /'
    echo ""
    
    # Positions
    echo "💼 POSITIONS:"
    if [ -f data/positions.json ]; then
        python3 -c "import json; p=json.load(open('data/positions.json')); print(f'  Open: {len(p)}') if p else print('  None')" 2>/dev/null
    else
        echo "  None"
    fi
    echo ""
    
    echo "Press Ctrl+C to exit"
    sleep 5
done
