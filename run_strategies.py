#!/usr/bin/env python3
"""Run all trading strategies."""
import sys
sys.path.insert(0, '/home/ubuntu/trading-bot')

from agents.momentum_trader import momentum_strategy
from agents.trump_trader import trump_strategy
from agents.merger_arb import merger_arb_strategy
from agents.inefficiency_trader import inefficiency_strategy

if len(sys.argv) < 2:
    print("Usage: python run_strategies.py [strategy]")
    print("\nAvailable strategies:")
    print("  momentum      - Day trading breakouts")
    print("  trump         - Trump policy signals")
    print("  smartmoney    - Institutional order flow (DISABLED - pandas bug)")
    print("  mergerarb     - Merger arbitrage")
    print("  inefficiency  - Market inefficiencies")
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
    
elif strategy == "smartmoney":
    print("=" * 60)
    print("SMART MONEY TRADER (DISABLED)")
    print("=" * 60)
    print("Strategy disabled due to pandas bug - see CURSOR_QUICKSTART.txt")
    result = {'status': 'disabled', 'reason': 'pandas bug in order block detection'}
    
elif strategy == "mergerarb":
    print("=" * 60)
    print("MERGER ARBITRAGE")
    print("=" * 60)
    result = merger_arb_strategy(10000)
    print(f"\nResult: {result}")
    
elif strategy == "inefficiency":
    print("=" * 60)
    print("INEFFICIENCY TRADER")
    print("=" * 60)
    result = inefficiency_strategy(10000)
    print(f"\nResult: {result}")
    
else:
    print(f"Unknown strategy: {strategy}")
    sys.exit(1)
