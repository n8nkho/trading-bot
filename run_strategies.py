#!/usr/bin/env python3
"""Run all trading strategies."""
import sys
sys.path.insert(0, '/home/ubuntu/trading-bot')

from agents.momentum_trader import momentum_strategy
from agents.trump_trader import trump_strategy
from agents.merger_arb import merger_arb_strategy
from agents.inefficiency_trader import inefficiency_strategy
from agents.smart_money_trader import smart_money_strategy
from agents.earnings_drift import earnings_drift_strategy
from agents.insider_tracker import insider_buying_strategy
from agents.squeeze_detector import squeeze_detector_strategy
from agents.sector_rotation import sector_rotation_strategy
from agents.vwap_reversion import vwap_reversion_strategy
from agents.flow_tracker import flow_tracker_strategy

if len(sys.argv) < 2:
    print("Usage: python run_strategies.py [strategy]")
    print("\nAvailable strategies:")
    print("  momentum      - Day trading breakouts")
    print("  trump         - Trump policy signals")
    print("  smartmoney    - Institutional order flow (paper signals only)")
    print("  mergerarb     - Merger arbitrage")
    print("  inefficiency  - Market inefficiencies")
    print("  earnings      - Earnings drift continuation")
    print("  insider       - Insider buying tracker")
    print("  squeeze       - Short squeeze detector")
    print("  sector        - Sector rotation detector")
    print("  vwap          - VWAP mean reversion")
    print("  flow          - Options flow tracker (sample data)")
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
    print("SMART MONEY TRADER (PAPER SIGNALS)")
    print("=" * 60)
    result = smart_money_strategy(10000)
    print(f"\nSignals ({len(result)}):")
    for r in result:
        print(f"  {r['ticker']}: {r['action']} conf={r['confidence']:.2f} size=${r['position_size']:.0f} regime={r['regime']}")

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

elif strategy == "earnings":
    print("=" * 60)
    print("EARNINGS DRIFT STRATEGY")
    print("=" * 60)
    result = earnings_drift_strategy(10000)
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

elif strategy == "insider":
    print("=" * 60)
    print("INSIDER BUYING STRATEGY")
    print("=" * 60)
    result = insider_buying_strategy(10000)
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

elif strategy == "squeeze":
    print("=" * 60)
    print("SHORT SQUEEZE STRATEGY")
    print("=" * 60)
    result = squeeze_detector_strategy(10000)
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

elif strategy == "sector":
    print("=" * 60)
    print("SECTOR ROTATION STRATEGY")
    print("=" * 60)
    result = sector_rotation_strategy(10000)
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(
            f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}, "
            f"sector={c.get('sector', 'N/A')}"
        )

elif strategy == "vwap":
    print("=" * 60)
    print("VWAP REVERSION STRATEGY")
    print("=" * 60)
    result = vwap_reversion_strategy(10000)
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

elif strategy == "flow":
    print("=" * 60)
    print("OPTIONS FLOW STRATEGY")
    print("=" * 60)
    result = flow_tracker_strategy(10000)
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

else:
    print(f"Unknown strategy: {strategy}")
    sys.exit(1)
