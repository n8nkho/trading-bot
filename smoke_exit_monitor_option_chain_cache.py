"""
Smoke test: ensure option chain caching prevents repeated option_chain calls.
"""

import pandas as pd
import importlib


def main():
    import agents.exit_monitor as em
    import json
    # Use configured watchlist ticker (no hard-coded tickers in this smoke script).
    with open("config/watchlist.json", "r") as f:
        quality_stocks = json.load(f).get("quality_stocks") or []
    if not quality_stocks:
        raise SystemExit("No tickers found in config/watchlist.json (quality_stocks empty).")
    underlying = str(quality_stocks[0].get("ticker")).strip().upper()

    # Reset cache
    em._OPTION_CHAIN_CACHE.clear()

    expiration = "2099-01-01"
    strike = 100.0
    call = True
    from utils.option_contract_schema import format_option_symbol
    option_symbol = format_option_symbol(underlying_ticker=underlying, expiration=expiration, strike=strike, call=call)

    # Fake chain maker that counts calls.
    call_counter = {"n": 0}

    class _FakeChain:
        def __init__(self, last_price):
            self.calls = pd.DataFrame(
                [
                    {
                        "strike": strike,
                        "lastPrice": last_price,
                        "bid": last_price * 0.99,
                        "ask": last_price * 1.01,
                        "volume": 200,
                        "delta": 0.6,
                        "impliedVolatility": 0.3,
                    }
                ]
            )
            self.puts = pd.DataFrame(
                [
                    {
                        "strike": strike,
                        "lastPrice": last_price,
                        "bid": last_price * 0.99,
                        "ask": last_price * 1.01,
                        "volume": 200,
                        "delta": 0.4,
                        "impliedVolatility": 0.3,
                    }
                ]
            )

    class _FakeTicker:
        def __init__(self, sym):
            self.sym = sym

        def option_chain(self, expiration_date):
            call_counter["n"] += 1
            return _FakeChain(last_price=2.0)

    em.yf.Ticker = lambda sym: _FakeTicker(sym)

    # Two positions with same underlying+expiration, so chain should be fetched once.
    positions = [
        {
            "ticker": option_symbol,
            "type": "OPTION",
            "underlying_ticker": underlying,
            "qty": 2,
            "entry_premium": 1.0,
            "expiration_date": expiration,
            "strike": strike,
            "call": call,
            "tiers_sold": {"tier1": False, "tier2": False, "tier3": False},
        },
        {
            "ticker": option_symbol,
            "type": "OPTION",
            "underlying_ticker": underlying,
            "qty": 1,
            "entry_premium": 1.0,
            "expiration_date": expiration,
            "strike": strike,
            "call": call,
            "tiers_sold": {"tier1": False, "tier2": False, "tier3": False},
        },
    ]

    decisions = em.monitor_positions(positions)
    assert isinstance(decisions, list) and decisions
    assert call_counter["n"] == 1, f"Expected one option_chain call, got {call_counter['n']}"

    print("[smoke] smoke_exit_monitor_option_chain_cache: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

