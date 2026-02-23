#!/bin/bash
cd ~/trading-bot
source venv/bin/activate

{
    echo "DAILY HEALTH REPORT - $(date)"
    echo "================================"
    python check_health.py
    echo ""
    echo "ALERTS:"
    python check_alerts.py
} > logs/daily_health_$(date +%Y%m%d).log

# Optional: Email it
# mail -s "Trading Bot Health Report" your@email.com < logs/daily_health_$(date +%Y%m%d).log
