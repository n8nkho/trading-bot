#!/usr/bin/env python3
"""Run all trading strategies. Each strategy runs in try/except; one failure does not stop others."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

def _run_safe(name, fn, *args, **kwargs):
    """Run strategy; return (result, error). On exception return (None, str(e))."""
    try:
        return (fn(*args, **kwargs), None)
    except Exception as e:
        import traceback
        sys.stderr.write(f"Strategy {name} failed: {e}\n")
        traceback.print_exc()
        return (None, str(e))


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

# License tier gate: only run if this strategy is allowed for the current plan
try:
    from config.license import get_plan
    from config.tiers import strategy_allowed
    plan = get_plan()
    if not strategy_allowed(strategy, plan.tier):
        print(f"Strategy '{strategy}' is not included in your license tier ({plan.tier}). Upgrade to run this strategy.")
        sys.exit(1)
except Exception:
    pass  # If license/tiers unavailable, allow (e.g. master dev)

if strategy == "momentum":
    from agents.momentum_trader import momentum_strategy
    print("=" * 60)
    print("MOMENTUM DAY TRADER")
    print("=" * 60)
    result, err = _run_safe("momentum", momentum_strategy)
    if err:
        sys.exit(1)
    print(f"\nResult: {result}")

elif strategy == "trump":
    from agents.trump_trader import trump_strategy
    print("=" * 60)
    print("TRUMP POLICY TRADER")
    print("=" * 60)
    result, err = _run_safe("trump", trump_strategy, 10000)
    if err:
        sys.exit(1)
    print(f"\nResult: {result}")

elif strategy == "smartmoney":
    from agents.smart_money_trader import smart_money_strategy
    print("=" * 60)
    print("SMART MONEY TRADER (PAPER SIGNALS)")
    print("=" * 60)
    result, err = _run_safe("smartmoney", smart_money_strategy, 10000)
    if err:
        sys.exit(1)
    result = result or []
    print(f"\nSignals ({len(result)}):")
    for r in result:
        print(f"  {r['ticker']}: {r['action']} conf={r['confidence']:.2f} size=${r['position_size']:.0f} regime={r['regime']}")

elif strategy == "mergerarb":
    from agents.merger_arb import merger_arb_strategy
    print("=" * 60)
    print("MERGER ARBITRAGE")
    print("=" * 60)
    result, err = _run_safe("mergerarb", merger_arb_strategy, 10000)
    if err:
        sys.exit(1)
    print(f"\nResult: {result}")

elif strategy == "inefficiency":
    from agents.inefficiency_trader import inefficiency_strategy
    print("=" * 60)
    print("INEFFICIENCY TRADER")
    print("=" * 60)
    result, err = _run_safe("inefficiency", inefficiency_strategy, 10000)
    if err:
        sys.exit(1)
    result = result if result is not None else []
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        conf = c.get("analysis", {}).get("confidence", 0)
        print(f"  {c.get('ticker', '?')}: conf={conf:.2f}")

elif strategy == "earnings":
    from agents.earnings_drift import earnings_drift_strategy
    print("=" * 60)
    print("EARNINGS DRIFT STRATEGY")
    print("=" * 60)
    result, err = _run_safe("earnings", earnings_drift_strategy, 10000)
    if err:
        sys.exit(1)
    result = result or []
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

elif strategy == "insider":
    from agents.insider_tracker import insider_buying_strategy
    print("=" * 60)
    print("INSIDER BUYING STRATEGY")
    print("=" * 60)
    result, err = _run_safe("insider", insider_buying_strategy, 10000)
    if err:
        sys.exit(1)
    result = result or []
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

elif strategy == "squeeze":
    from agents.squeeze_detector import squeeze_detector_strategy
    print("=" * 60)
    print("SHORT SQUEEZE STRATEGY")
    print("=" * 60)
    result, err = _run_safe("squeeze", squeeze_detector_strategy, 10000)
    if err:
        sys.exit(1)
    result = result or []
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

elif strategy == "sector":
    from agents.sector_rotation import sector_rotation_strategy
    print("=" * 60)
    print("SECTOR ROTATION STRATEGY")
    print("=" * 60)
    result, err = _run_safe("sector", sector_rotation_strategy, 10000)
    if err:
        sys.exit(1)
    result = result or []
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(
            f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}, "
            f"sector={c.get('sector', 'N/A')}"
        )

elif strategy == "vwap":
    from agents.vwap_reversion import vwap_reversion_strategy
    print("=" * 60)
    print("VWAP REVERSION STRATEGY")
    print("=" * 60)
    result, err = _run_safe("vwap", vwap_reversion_strategy, 10000)
    if err:
        sys.exit(1)
    result = result or []
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

elif strategy == "flow":
    from agents.flow_tracker import flow_tracker_strategy
    print("=" * 60)
    print("OPTIONS FLOW STRATEGY")
    print("=" * 60)
    result, err = _run_safe("flow", flow_tracker_strategy, 10000)
    if err:
        sys.exit(1)
    result = result or []
    print(f"\nCandidates ({len(result)}):")
    for c in result[:10]:
        print(f"  {c['ticker']}: conf={c['analysis']['confidence']:.2f}")

else:
    print(f"Unknown strategy: {strategy}")
    sys.exit(1)
