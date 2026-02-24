#!/usr/bin/env python3
"""Simple wrapper to run momentum and Trump strategies."""
import sys
sys.path.insert(0, '/home/ubuntu/trading-bot')

from agents.momentum_trader import momentum_strategy
from agents.trump_trader import trump_strategy

if len(sys.argv) < 2:
    print("Usage: python run_strategies.py [momentum|trump]")
    print("  momentum - Scan for day trading breakouts")
    print("  trump    - Monitor Trump policy signals")
    sys.exit(1)

strategy = sys.argv[1]

if strategy == "momentum":
    print("=" * 60)
    print("MOMENTUM DAY TRADER")
    print("=" * 60)
    result = momentum_strategy()
    print(f"\nResult: {result}")
    
elif strategy == "trump":
    print("=" * 60)
    print("TRUMP POLICY TRADER")
    print("=" * 60)
    result = trump_strategy(10000)
    print(f"\nResult: {result}")
    
else:
    print(f"Unknown strategy: {strategy}")
    sys.exit(1)
