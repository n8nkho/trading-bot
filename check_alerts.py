#!/usr/bin/env python3
"""Check for alert conditions"""
import json
import os
from datetime import datetime, timedelta

alerts = []

# Check 1: No recent activity
for log_file in ['logs/screener.log', 'logs/sniper.log']:
    if os.path.exists(log_file):
        mtime = datetime.fromtimestamp(os.path.getmtime(log_file))
        if datetime.now() - mtime > timedelta(hours=24):
            alerts.append(f"⚠️  {log_file} not updated in 24h")

# Check 2: Circuit breaker active
if os.path.exists('data/risk_status.json'):
    with open('data/risk_status.json') as f:
        risk = json.load(f)
    if risk.get('circuit_breaker'):
        alerts.append("🚨 CIRCUIT BREAKER ACTIVE!")

# Check 3: High consecutive losses
    if risk.get('consecutive_losses', 0) >= 3:
        alerts.append(f"⚠️  {risk['consecutive_losses']} consecutive losses")

# Check 4: Low disk space
import shutil
total, used, free = shutil.disk_usage("/")
if (used / total) > 0.9:
    alerts.append("🚨 DISK SPACE CRITICAL!")

# Print alerts
if alerts:
    print("🚨 ALERTS:")
    for alert in alerts:
        print(f"  {alert}")
else:
    print("✅ No alerts - all systems normal")
