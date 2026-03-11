#!/usr/bin/env python3
"""Sync Alpaca positions to local data"""
from alpaca.trading.client import TradingClient
import os
import json
from datetime import datetime

# Load env
with open(.env) as f:
    for line in f:
        if ALPACA in line and not line.startswith(#):
            key, val = line.strip().split(=, 1)
            os.environ[key] = val

# Get positions
client = TradingClient(
    os.getenv(ALPACA_API_KEY),
    os.getenv(ALPACA_SECRET_KEY),
    paper=True
)

# Load existing positions to preserve entry_time
existing_entry_times = {}
try:
    with open(data/positions.json) as f:
        existing = json.load(f)
    for p in existing:
        if p.get(ticker) and p.get(entry_time):
            existing_entry_times[p[ticker]] = p[entry_time]
except Exception:
    pass

positions = client.get_all_positions()
pos_list = []

for pos in positions:
    ticker = pos.symbol
    # Preserve existing entry_time if already known; otherwise use now
    entry_time = existing_entry_times.get(ticker, datetime.now().isoformat())
    pos_list.append({
        ticker: ticker,
        qty: float(pos.qty),
        entry_price: float(pos.avg_entry_price),
        current_price: float(pos.current_price),
        pnl: float(pos.unrealized_pl),
        pnl_pct: (float(pos.unrealized_pl) / float(pos.cost_basis)) * 100,
        entry_time: entry_time,
        cost_basis: float(pos.cost_basis)
    })

with open(data/positions.json, w) as f:
    json.dump(pos_list, f, indent=2)

print(f"✅ Synced {len(pos_list)} positions")
