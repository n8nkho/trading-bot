#!/usr/bin/env python3
"""Quick bot health check"""
import os
import json
from datetime import datetime, timedelta
import subprocess

print("=" * 60)
print("🏥 BOT HEALTH CHECK")
print("=" * 60)

# 1. Check processes
print("\n1. PROCESS STATUS:")
try:
    result = subprocess.run(['pgrep', '-f', 'dashboard/app.py'], capture_output=True)
    if result.returncode == 0:
        print("   ✅ Dashboard: RUNNING")
    else:
        print("   ❌ Dashboard: STOPPED")
except:
    print("   ⚠️  Dashboard: UNKNOWN")

try:
    result = subprocess.run(['systemctl', 'is-active', 'ollama'], capture_output=True, text=True)
    if 'active' in result.stdout:
        print("   ✅ Ollama: RUNNING")
    else:
        print("   ❌ Ollama: STOPPED")
except:
    print("   ⚠️  Ollama: UNKNOWN")

# 2. Check cron jobs
print("\n2. AUTOMATION STATUS:")
result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
if 'orchestrator.py' in result.stdout:
    print("   ✅ Cron jobs: CONFIGURED")
    cron_count = result.stdout.count('orchestrator.py')
    print(f"   📋 Active jobs: {cron_count}")
else:
    print("   ❌ Cron jobs: NOT CONFIGURED")

# 3. Check data files
print("\n3. DATA STATUS:")
files = {
    'Positions': 'data/positions.json',
    'Decisions Log': 'data/decisions_log.jsonl',
    'Watchlist': 'config/watchlist.json'
}
for name, path in files.items():
    if os.path.exists(path):
        size = os.path.getsize(path)
        print(f"   ✅ {name}: {size} bytes")
    else:
        print(f"   ⚠️  {name}: MISSING")

# 4. Check recent activity
print("\n4. RECENT ACTIVITY:")
log_files = [
    ('Screener', 'logs/screener.log'),
    ('Sniper', 'logs/sniper.log'),
    ('Monitor', 'logs/monitor.log')
]
for name, path in log_files:
    if os.path.exists(path):
        mtime = os.path.getmtime(path)
        age = datetime.now() - datetime.fromtimestamp(mtime)
        if age.total_seconds() < 3600:  # Less than 1 hour
            print(f"   ✅ {name}: {int(age.total_seconds()/60)} min ago")
        elif age.days < 1:
            print(f"   ⚠️  {name}: {int(age.total_seconds()/3600)} hours ago")
        else:
            print(f"   ❌ {name}: {age.days} days ago")
    else:
        print(f"   ⚠️  {name}: NO LOGS")

# 5. Check disk space
print("\n5. SYSTEM RESOURCES:")
import shutil
total, used, free = shutil.disk_usage("/")
pct = (used / total) * 100
print(f"   Disk: {used//10**9}GB used / {total//10**9}GB total ({pct:.1f}%)")
if pct > 90:
    print("   ❌ CRITICAL: Disk space low!")
elif pct > 75:
    print("   ⚠️  WARNING: Disk space getting low")
else:
    print("   ✅ Disk space: OK")

# 6. Check positions
print("\n6. CURRENT POSITIONS:")
if os.path.exists('data/positions.json'):
    with open('data/positions.json') as f:
        try:
            positions = json.load(f)
            if positions:
                print(f"   📊 Open positions: {len(positions)}")
                for p in positions:
                    print(f"      • {p.get('ticker', 'UNKNOWN')}: ${p.get('entry_price', 0)}")
            else:
                print("   💤 No open positions")
        except:
            print("   ⚠️  Can't read positions file")
else:
    print("   💤 No positions file")

# 7. Performance summary
print("\n7. PERFORMANCE (if available):")
if os.path.exists('data/decisions_log.jsonl'):
    try:
        with open('data/decisions_log.jsonl') as f:
            lines = f.readlines()
            if lines:
                recent = [json.loads(l) for l in lines[-20:]]  # Last 20
                wins = sum(1 for t in recent if t.get('outcome') == 'WIN')
                total = len([t for t in recent if 'outcome' in t])
                if total > 0:
                    win_rate = (wins / total) * 100
                    print(f"   📈 Win rate (last 20): {win_rate:.1f}%")
                else:
                    print("   ⏳ Not enough completed trades yet")
            else:
                print("   ⏳ No trades logged yet")
    except:
        print("   ⚠️  Can't read decisions log")
else:
    print("   ⏳ No decision log yet")

# 8. API COSTS & SAVINGS (if available):
print("\n8. API COSTS & SAVINGS (if available):")
api_costs_path = 'data/api_costs.jsonl'
if os.path.exists(api_costs_path):
    try:
        today = datetime.now().date()
        calls, total_cost, cached_tokens, total_tokens = 0, 0.0, 0, 0
        with open(api_costs_path) as f:
            for line in f:
                record = json.loads(line)
                record_date = datetime.fromisoformat(record['date']).date()
                if record_date == today:
                    calls += 1
                    total_cost += record.get('cost', 0)
                    cached_tokens += record.get('cached_tokens', 0)
                    total_tokens += record.get('input_tokens', 0) + record.get('output_tokens', 0)
        
        if calls > 0:
            cache_hit_rate = (cached_tokens / total_tokens) * 100 if total_tokens > 0 else 0
            savings = (total_tokens - cached_tokens) * 0.01  # Assuming $0.01 per token saved
            print(f"   📊 API Costs Today:")
            print(f"      Calls: {calls}")
            print(f"      Cost: ${total_cost:.2f} ({cache_hit_rate:.1f}% cached)")
            print(f"      Savings: ${savings:.2f}")
        else:
            print("   ⏳ No API calls logged today")
    except Exception as e:
        print(f"   ⚠️  Can't read API costs: {e}")
else:
    print("   ⏳ No API cost log yet")
print("Health check complete!")
print("=" * 60)
