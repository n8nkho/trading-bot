import json
import os
from datetime import datetime, timedelta


def _as_float(x):
    try:
        return float(x)
    except Exception:
        return None


def main():
    portfolio_value = float(os.getenv("SMOKE_PORTFOLIO_VALUE", "10000"))
    skip_live_screener = os.getenv("SMOKE_SKIP_LIVE_SCREENER", "0") == "1"
    print(f"[smoke] portfolio_value={portfolio_value}")

    # Use configured tickers/pair labels (no hard-coded tickers in this smoke test).
    with open("config/watchlist.json", "r") as f:
        quality_stocks = json.load(f).get("quality_stocks") or []
    primary_ticker = str(quality_stocks[0].get("ticker")).strip().upper() if quality_stocks else ""
    secondary_ticker = str(quality_stocks[1].get("ticker")).strip().upper() if len(quality_stocks) > 1 else primary_ticker

    with open("config/market_assets.json", "r") as f:
        market_assets = json.load(f) or {}
    fx_pair_label = (market_assets.get("forex_hedger") or {}).get("pair_label")

    # Keep this test deterministic: risk_guardian now persists state across runs.
    # Reset it so other smoke tests don't affect contract sizing.
    try:
        from pathlib import Path
        risk_state_file = Path("data") / "risk_guardian_state.json"
        if risk_state_file.exists():
            risk_state_file.unlink()
    except Exception:
        pass

    # Import after reading env so it can be used by imports if needed
    from agents.screener_agent import run_screener
    from agents.entry_agent import evaluate_entry
    from agents.risk_guardian import check_risk_limits
    from agents.exit_monitor import monitor_positions
    # Some modules (e.g. `agents.vix_insurance`) initialize Alpaca clients at import-time
    # using `APCA_API_KEY_ID`/`APCA_API_SECRET_KEY`. Provide dummy values so imports
    # succeed in a smoke-test environment.
    os.environ.setdefault("APCA_API_KEY_ID", "smoke_dummy_key")
    os.environ.setdefault("APCA_API_SECRET_KEY", "smoke_dummy_secret")
    import orchestrator

    # 1) Screener schema contract test (covers: current_price propagation)
    #    Note: live screening may produce zero candidates depending on market conditions.
    candidates = []
    if skip_live_screener:
        print("[smoke] skipping live screener step (SMOKE_SKIP_LIVE_SCREENER=1)")
    else:
        print("[smoke] running screener_agent.run_screener() (live) ...")
        candidates = run_screener()
        print(f"[smoke] candidates_found={len(candidates)}")

    if candidates:
        top = candidates[:3]
        for c in top:
            assert "current_price" in c, f"Missing current_price for {c.get('ticker')}"
            assert _as_float(c["current_price"]) is not None, f"Invalid current_price for {c.get('ticker')}"
            assert "analysis" in c and isinstance(c["analysis"], dict), f"Missing analysis dict for {c.get('ticker')}"
            assert "confidence" in c["analysis"], f"Missing analysis.confidence for {c.get('ticker')}"

        # 2) Entry decisions (stock path) contract test (also covers current_price usage)
        print("[smoke] running entry_agent.evaluate_entry(top_candidates) ...")
        decisions = evaluate_entry(top, portfolio_value=portfolio_value)
        assert isinstance(decisions, list) and decisions, "evaluate_entry should return non-empty list"

        buy_decisions = [d for d in decisions if d.get("action") == "BUY"]
        print(f"[smoke] buy_decisions={len(buy_decisions)} skip_or_other={len(decisions) - len(buy_decisions)}")

        # 3) Risk check on any BUYs (should not crash)
        approved = []
        portfolio_data = {
            "equity": portfolio_value,
            "positions": [],
            "today_pnl": 0,
            "week_pnl": None,
        }
        for d in buy_decisions:
            new_position = {
                "ticker": d["ticker"],
                "size": d["shares"],
                "value": d["position_size"],
                "sector": d.get("sector", "Unknown"),
            }
            risk = check_risk_limits(portfolio_data, new_position)
            assert "approved" in risk, "risk_guardian.check_risk_limits must return approved key"
            if risk["approved"]:
                approved.append((d, risk))

        print(f"[smoke] approved_by_risk={len(approved)}")

        # 4) Exit-monitor smoke on mock positions built from approved decisions.
        positions = []
        now = datetime.now()
        for d, _risk in approved[:2]:
            positions.append(
                {
                    "ticker": d["ticker"],
                    "type": "STOCK",
                    "entry_price": d["entry_price"],
                    "qty": d["shares"],
                    "entry_time": (now - timedelta(days=1, hours=1)).isoformat(),
                    "tiers_sold": {"tier1": False, "tier2": False, "tier3": False},
                }
            )

        if positions:
            print("[smoke] running exit_monitor.monitor_positions(mock_positions) (live prices) ...")
            exit_decisions = monitor_positions(positions)
            assert isinstance(exit_decisions, list) and exit_decisions, "exit_monitor should return decisions list"
            print("[smoke] exit_actions=" + ", ".join(sorted({d["action"] for d in exit_decisions})))
        else:
            print("[smoke] no approved positions; skipping exit_monitor step.")
    else:
        print("[smoke] no candidates found from live screener; skipping live component checks.")

    # 5) Control-flow smoke (deterministic, monkeypatched)
    #    Covers: (a) orchestrator parallel analysis indexing bug, (b) current_price contract,
    #    (c) defensive `action` filtering.
    print("[smoke] running orchestrator.run_daily_screening() (control-flow, monkeypatched) ...")

    import orchestrator as orch_mod

    # Prepare deterministic candidate set (one STOCK candidate, one OPTION candidate lacking `action`)
    mock_candidates = [
        {
            "ticker": primary_ticker,
            "sector": "Technology",
            "current_price": 100.0,
            "drop_pct": -10.0,
            "rsi": 25.0,
            "volume_ratio": 2.0,
            "news": ["mock headline"],
            "vision_signal": None,
            "analysis": {"confidence": 0.9},
        },
        {
            "ticker": secondary_ticker,
            "sector": "Technology",
            "current_price": 200.0,
            "drop_pct": -12.0,
            "rsi": 20.0,
            "volume_ratio": 2.5,
            "news": ["mock headline"],
            "vision_signal": None,
            "analysis": {"confidence": 0.9},
        },
    ]

    orch_mod.run_screener = lambda: mock_candidates

    class _PassthroughRecursiveScreener:
        def screen_candidates(self, candidates, portfolio_nav=None):
            return list(candidates or [])

    orch_mod.RecursiveScreener = lambda data_dir=None: _PassthroughRecursiveScreener()
    orch_mod.check_twitter_sentiment = lambda ticker, confidence: "BULLISH"
    orch_mod.quick_fundamental_check = lambda ticker, confidence: {
        "fundamental_approved": True,
        "risk_score": 10,
        "reason": "mock ok",
        "adjusted_confidence": confidence,
        "cost": 0,
    }

    def fake_evaluate_entry(candidates, portfolio_value):
        # Use candidate["current_price"] to ensure the current_price contract is exercised.
        decisions = []
        for c in candidates:
            cp = c["current_price"]  # KeyError here would fail the smoke test.
            if c["ticker"] == primary_ticker:
                shares = 4
                position_size = shares * cp  # keep this small enough to pass risk_guardian limits in this smoke test
                decisions.append(
                    {
                        "ticker": c["ticker"],
                        "action": "BUY",
                        "confidence": c["analysis"]["confidence"],
                        "reasoning": "mock entry criteria (control-flow smoke)",
                        "reason": "mock entry criteria",
                        "position_size": position_size,
                        "shares": shares,
                        "entry_price": cp,
                        "timestamp": datetime.now().isoformat(),
                        "trade_type": "STOCK",
                    }
                )
            else:
                # OPTION-style decision dict WITHOUT `action` to verify orchestrator filtering.
                decisions.append(
                    {
                        "ticker": c["ticker"],
                        "trade_type": "OPTION",
                        "option_details": {"type": "OPTION", "strike": cp},
                    }
                )
        return decisions

    orch_mod.evaluate_entry = fake_evaluate_entry

    # Mock account + execution so orchestrator doesn't hit Alpaca.
    orch_mod.get_account_info = lambda: {
        "buying_power": 100000.0,
        "equity": portfolio_value,
        "cash": 100000.0,
        "portfolio_value": portfolio_value,
        "position_count": 0,
    }
    orch_mod.load_positions = lambda: []
    orch_mod.load_current_params = lambda: {"rsi_threshold": 40, "stop_loss_pct": -2.0, "take_profit_pct": 5.0}
    orch_mod.check_risk_limits = check_risk_limits  # use real risk_guardian for contract

    orch_mod.execute_buy_order = lambda ticker, shares, entry_price: {
        "success": True,
        "order_id": "smoke_order_id",
        "filled_qty": shares,
        "filled_price": entry_price,
        "status": "filled",
        "error": None,
    }
    orch_mod.add_position = lambda position: None

    result = orch_mod.run_daily_screening(portfolio_value=portfolio_value)
    assert isinstance(result, dict), "orchestrator.run_daily_screening must return dict"
    print("[smoke] orchestrator_controlflow_keys=" + ", ".join(sorted(result.keys())))
    print(f"[smoke] orchestrator_controlflow_candidates_found={result.get('candidates_found')}")
    if result.get("error"):
        print(f"[smoke] orchestrator_controlflow_error={result.get('error')} (type={result.get('error_type')})")
    print(f"[smoke] orchestrator_controlflow_approved_trades={len(result.get('approved_trades', []))}")
    if len(result.get("approved_trades", [])) == 0:
        rejected = result.get("rejected_trades", [])
        print("[smoke] orchestrator_controlflow_rejected_sample=" + json.dumps(rejected[:3], indent=2))

    # 6) Option trading path smoke test (deterministic, exercises option order + exit pricing)
    print("[smoke] option-path smoke test (deterministic, monkeypatched) ...")
    import orchestrator as orch_mod2
    import agents.exit_monitor as exit_mod
    import agents.commodity_trader as commodity_mod
    import agents.forex_hedger as forex_mod
    import pandas as pd

    class _FakeOrder:
        def __init__(self, qty, filled_avg_price):
            self.id = "fake_order_id"
            self.status = "filled"
            self.filled_qty = qty
            self.filled_avg_price = filled_avg_price

    class _FakeTradingClient:
        def submit_order(self, order_data):
            # order_data.qty should be contract count for options in Alpaca.
            filled_price = float(getattr(order_data, "limit_price", None) or 1.0)
            return _FakeOrder(qty=getattr(order_data, "qty", 1), filled_avg_price=filled_price)

    saved_positions = []
    orch_mod2.run_screener = lambda: mock_candidates
    orch_mod2.RecursiveScreener = lambda data_dir=None: _PassthroughRecursiveScreener()
    orch_mod2.check_twitter_sentiment = lambda ticker, confidence: "BULLISH"
    orch_mod2.quick_fundamental_check = lambda ticker, confidence: {
        "fundamental_approved": True,
        "risk_score": 10,
        "reason": "mock ok",
        "adjusted_confidence": confidence,
        "cost": 0,
    }

    def fake_evaluate_entry_option_path(candidates, portfolio_value):
        decisions = []
        for c in candidates:
            cp = c["current_price"]
            if c["ticker"] == primary_ticker:
                decisions.append(
                    {
                        "ticker": c["ticker"],
                        "action": "BUY",
                        "trade_type": "STOCK",
                        "confidence": c["analysis"]["confidence"],
                        "reasoning": "stock smoke buy",
                        "position_size": 200.0,
                        "shares": 2,
                        "entry_price": 100.0,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            else:
                # OPTION decision WITH action (so orchestrator executes it)
                decisions.append(
                    {
                        "ticker": c["ticker"],  # underlying
                        "action": "BUY",
                        "trade_type": "OPTION",
                        "confidence": c["analysis"]["confidence"],
                        "reasoning": "option smoke buy",
                        "strike": 100.0,
                        "expiration": "2099-01-01",
                        "contracts": 2,
                        "call": True,
                        "entry_price": 1.0,      # premium
                        "position_size": 200.0,  # 2 contracts * $1.00 * 100
                        "option_details": {"premium": 1.0},
                        "timestamp": datetime.now().isoformat(),
                    }
                )
        return decisions

    orch_mod2.evaluate_entry = fake_evaluate_entry_option_path
    orch_mod2.get_account_info = lambda: {
        "buying_power": 100000.0,
        "equity": portfolio_value,
        "cash": 100000.0,
        "portfolio_value": portfolio_value,
        "position_count": 0,
    }
    orch_mod2.load_positions = lambda: []
    orch_mod2.load_current_params = lambda: {"rsi_threshold": 40, "stop_loss_pct": -2.0, "take_profit_pct": 15.0}
    orch_mod2.execute_buy_order = lambda ticker, shares, entry_price: {
        "success": True,
        "order_id": "smoke_stock_order",
        "filled_qty": shares,
        "filled_price": entry_price,
        "status": "filled",
        "error": None,
    }
    orch_mod2.add_position = lambda position: saved_positions.append(position)
    orch_mod2.alpaca_client = _FakeTradingClient()

    orch_result = orch_mod2.run_daily_screening(portfolio_value=portfolio_value)
    assert isinstance(orch_result, dict)
    assert any(p.get("type") == "OPTION" for p in saved_positions), "No OPTION position saved during option-path smoke test"

    option_pos = next(p for p in saved_positions if p.get("type") == "OPTION")
    assert option_pos["qty"] == 2, "Expected 2 option contracts in saved option position"

    # Monkeypatch yfinance option_chain pricing for deterministic exit behavior.
    # Make the option premium jump to +60% so tier1 (+50%) triggers: SELL_50%.
    class _FakeChain:
        def __init__(self, strike, current_premium):
            self.calls = pd.DataFrame(
                [
                    {"strike": strike, "lastPrice": current_premium, "bid": current_premium * 0.99, "ask": current_premium * 1.01, "volume": 200, "delta": 0.6, "impliedVolatility": 0.3}
                ]
            )
            self.puts = pd.DataFrame(
                [
                    {"strike": strike, "lastPrice": current_premium, "bid": current_premium * 0.99, "ask": current_premium * 1.01, "volume": 200, "delta": 0.4, "impliedVolatility": 0.3}
                ]
            )

    class _FakeUnderlyingTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def option_chain(self, expiration_date):
            return _FakeChain(option_pos["strike"], current_premium=option_pos["entry_premium"] * 1.6)

    exit_mod.yf.Ticker = lambda sym: _FakeUnderlyingTicker(sym)

    exit_decisions = exit_mod.monitor_positions([option_pos])
    assert isinstance(exit_decisions, list) and exit_decisions
    assert exit_decisions[0]["action"].startswith("SELL"), "Expected an exit SELL decision for option-path smoke test"
    assert exit_decisions[0]["tier"] == "tier1", "Expected tier1 exit for +60% option premium"
    assert exit_decisions[0]["sell_qty"] == int(option_pos["qty"] * 0.50), "Expected SELL_50% contract qty"

    # 7) Commodities + Forex hedging recommendation structure tests
    print("[smoke] commodities + forex recommendation structure tests ...")
    commodity_mod.get_usd_strength = lambda: 88.0
    from agents import vix_insurance as vix_mod
    commodity_mod.get_current_vix = lambda: 30.0
    commodity_mod.get_gold_price = lambda: 1900.0
    commodity_mod.get_silver_price = lambda: 25.0
    comm = commodity_mod.commodity_hedge_strategy(10000.0)
    assert comm["action"] in {"INCREASE", "HOLD"}
    assert isinstance(comm, dict) and "positions" in comm if comm["action"] == "INCREASE" else True

    forex_mod.get_usd_strength = lambda: 101.0
    forex_mod.get_current_vix = lambda: 25.0
    # Patch forex rate retrieval
    forex_mod.yf.Ticker = lambda sym: type(
        "_FakeFXTicker",
        (),
        {"history": lambda self, period=None, interval=None: pd.DataFrame({"Close": [1.1]})},
    )()
    fx = forex_mod.forex_hedge_strategy(10000.0)
    assert fx["action"] in {"INCREASE", "HOLD"}
    if fx["action"] == "INCREASE":
        if fx_pair_label:
            assert fx["positions"][0]["pair"] == fx_pair_label

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

