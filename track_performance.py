#!/usr/bin/env python3
"""Track auto-trading performance."""
import sys
sys.path.insert(0, '/home/ubuntu/trading-bot')

import json
from datetime import datetime, timedelta
from pathlib import Path

def analyze_auto_trades():
    """Analyze all auto-executed trades."""
    
    # Find all auto_trades files
    files = sorted(Path('data').glob('auto_trades_*.json'))
    
    all_trades = []
    for file in files:
        with open(file) as f:
            data = json.load(f)
            all_trades.extend(data.get('trades', []))
    
    if not all_trades:
        print("No auto-executed trades yet!")
        return
    
    # Calculate stats
    total = len(all_trades)
    wins = len([t for t in all_trades if t.get('pnl', 0) > 0])
    losses = total - wins
    win_rate = (wins / total * 100) if total > 0 else 0
    
    total_pnl = sum(t.get('pnl', 0) for t in all_trades)
    avg_win = sum(t.get('pnl', 0) for t in all_trades if t.get('pnl', 0) > 0) / wins if wins > 0 else 0
    avg_loss = sum(t.get('pnl', 0) for t in all_trades if t.get('pnl', 0) < 0) / losses if losses > 0 else 0
    
    print("=" * 60)
    print("AUTO-TRADING PERFORMANCE")
    print("=" * 60)
    print(f"\nTotal trades: {total}")
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"Win rate: {win_rate:.1f}%")
    print(f"\nTotal P&L: ${total_pnl:.2f}")
    print(f"Average win: ${avg_win:.2f}")
    print(f"Average loss: ${avg_loss:.2f}")
    print(f"Profit factor: {abs(avg_win/avg_loss) if avg_loss != 0 else 0:.2f}")
    print("\nRecent trades:")
    for trade in all_trades[-5:]:
        print(f"  {trade.get('date')}: {trade.get('ticker')} ${trade.get('pnl', 0):+.2f}")
    print("=" * 60)

if __name__ == '__main__':
    analyze_auto_trades()
