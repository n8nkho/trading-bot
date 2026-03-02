#!/usr/bin/env python3
"""Verify hedging modules load and return expected shapes. No live orders."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    ok = True
    # Bonds
    try:
        from agents.bond_manager import get_market_regime, calculate_bond_target
        r = get_market_regime()
        assert r in ("RISK_ON", "RISK_OFF", "NEUTRAL"), r
        t = calculate_bond_target(100_000, r)
        assert isinstance(t, (int, float)) and t >= 0
        print("Bonds: OK")
    except Exception as e:
        print(f"Bonds: FAIL - {e}")
        ok = False
    # Commodities (may fail if OANDA not set)
    try:
        from agents.commodity_trader import should_buy_commodities
        from agents.vix_insurance import get_current_vix
        vix = get_current_vix()
        action, msg = should_buy_commodities(95.0, vix or 20)
        assert action in ("HOLD", "BUY_GOLD", "BUY_SILVER", "BUY_BOTH"), action
        print("Commodities: OK")
    except Exception as e:
        print(f"Commodities: FAIL - {e}")
        ok = False
    # Forex (stub-heavy; import only)
    try:
        from agents import forex_sniper
        print("Forex: OK (module load)")
    except Exception as e:
        print(f"Forex: FAIL - {e}")
        ok = False
    # Options
    try:
        from agents.entry_agent import get_options_chain
        out = get_options_chain("AAPL", 35)
        if out is None:
            print("Options: OK (no chain)")
        else:
            calls, exp = out
            print("Options: OK")
    except Exception as e:
        print(f"Options: FAIL - {e}")
        ok = False
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
