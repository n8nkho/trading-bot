#!/usr/bin/env python3
"""Sync Alpaca positions to local data"""
from alpaca.trading.client import TradingClient
import os
import json
from datetime import datetime
from pathlib import Path

# Run from project root (for cron compatibility)
PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)

# Load env
with open(PROJECT_ROOT / '.env') as f:
    for line in f:
        if 'ALPACA' in line and not line.startswith('#'):
            key, val = line.strip().split('=', 1)
            os.environ[key] = val

# Get positions
client = TradingClient(
    os.getenv('ALPACA_API_KEY'),
    os.getenv('ALPACA_SECRET_KEY'),
    paper=True
)

positions = client.get_all_positions()
pos_list = []

for pos in positions:
    pos_list.append({
        'ticker': pos.symbol,
        'qty': float(pos.qty),
        'entry_price': float(pos.avg_entry_price),
        'current_price': float(pos.current_price),
        'pnl': float(pos.unrealized_pl),
        'pnl_pct': (float(pos.unrealized_pl) / float(pos.cost_basis)) * 100,
        'entry_time': datetime.now().isoformat(),
        'cost_basis': float(pos.cost_basis)
    })

with open(PROJECT_ROOT / 'data' / 'positions.json', 'w') as f:
    json.dump(pos_list, f, indent=2)

print(f"✅ Synced {len(pos_list)} positions")
