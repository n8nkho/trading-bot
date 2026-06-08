#!/usr/bin/env python3
"""
Smoke: intraday sniper honors human-in-the-loop mode.

Runs the real ``orchestrator.py snipe`` CLI path with dependency stubs. In HITL
mode the opportunity must be queued and broker submit_order must not be called.
"""
from __future__ import annotations

import json
import os
import runpy
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, val in attrs.items():
        setattr(mod, key, val)
    sys.modules[name] = mod
    return mod


def _install_stubs() -> type:
    agents_pkg = _module("agents")
    agents_pkg.__path__ = []
    _module("agents.screener_agent", run_screener=lambda: [])
    _module("agents.entry_agent", evaluate_entry=lambda candidates, portfolio_value: [])
    _module("agents.exit_monitor", monitor_positions=lambda: {})
    _module(
        "agents.risk_guardian",
        check_risk_limits=lambda portfolio_data, new_position, strict_mode=False: {"approved": True},
        get_risk_limits=lambda: {},
        get_risk_status=lambda: {"consecutive_losses": 0, "circuit_breaker_active": False},
        update_consecutive_losses=lambda *args, **kwargs: None,
    )
    _module(
        "agents.performance_analyzer",
        track_decision=lambda *args, **kwargs: None,
        load_current_params=lambda: {"stop_loss_pct": -2.0, "take_profit_pct": 15.0},
    )
    _module(
        "agents.llama_watchdog",
        run_watchdog=lambda: {},
        preload_models=lambda: {"success": True},
        is_emergency_mode=lambda: False,
    )
    _module("agents.document_analyst", quick_fundamental_check=lambda *args, **kwargs: {})
    _module(
        "agents.intraday_sniper",
        scan_intraday_opportunities=lambda portfolio_value: [
            {"ticker": "SPY", "entry_price": 500.0, "metrics": {"volume_ratio": 3.0}}
        ],
        evaluate_quick_entry=lambda ticker, entry_price, metrics, portfolio_value: {
            "action": "BUY",
            "shares": 1,
            "position_value": entry_price,
            "reason": "smoke opportunity",
            "confidence": 0.99,
        },
    )
    _module("utils.grok_sentiment", check_twitter_sentiment=lambda *args, **kwargs: {})
    _module("utils.option_contract_schema", normalize_option_decision=lambda decision: decision)
    _module("utils.policy_profile", get_profile_bundle=lambda: {"execution": {"sniper_max_trades_per_run": 3}})
    _module("utils.trust_ledger", append_trust_event=lambda *args, **kwargs: None)
    _module(
        "utils.run_registry",
        log_screening_completed=lambda *args, **kwargs: None,
        log_screening_failed=lambda *args, **kwargs: None,
        log_screening_started=lambda *args, **kwargs: None,
    )
    _module(
        "utils.cost_calculator",
        get_daily_costs=lambda: {},
        get_monthly_projection=lambda: {},
        get_lifetime_costs=lambda: {},
        get_cost_per_trade=lambda: 0.0,
        generate_cost_report=lambda: {},
    )

    alpaca_pkg = _module("alpaca")
    alpaca_pkg.__path__ = []
    trading_pkg = _module("alpaca.trading")
    trading_pkg.__path__ = []

    class FakeAccount:
        buying_power = "1000000"
        equity = "100000"
        cash = "1000000"
        portfolio_value = "100000"

    class TradingClient:
        submit_count = 0

        def __init__(self, *args, **kwargs):
            pass

        def get_account(self):
            return FakeAccount()

        def get_all_positions(self):
            return []

        def submit_order(self, order_data):
            TradingClient.submit_count += 1
            raise AssertionError("HITL sniper must not submit broker orders")

    class MarketOrderRequest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class GetOrdersRequest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class OrderSide:
        BUY = "buy"
        SELL = "sell"

    class TimeInForce:
        DAY = "day"

    class QueryOrderStatus:
        CLOSED = "closed"

    _module("alpaca.trading.client", TradingClient=TradingClient)
    _module("alpaca.trading.requests", MarketOrderRequest=MarketOrderRequest, GetOrdersRequest=GetOrdersRequest)
    _module("alpaca.trading.enums", OrderSide=OrderSide, TimeInForce=TimeInForce, QueryOrderStatus=QueryOrderStatus)
    return TradingClient


def main() -> int:
    os.environ["FORTRESS_EXECUTION_MODE"] = "human_in_loop"
    os.environ["ALPACA_API_KEY"] = "smoke_key"
    os.environ["ALPACA_SECRET_KEY"] = "smoke_secret"
    os.environ["ALPACA_BASE_URL"] = "https://paper-api.alpaca.markets"
    client_cls = _install_stubs()

    old_argv = sys.argv[:]
    old_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as td:
        try:
            os.chdir(td)
            sys.path.insert(0, str(ROOT))
            sys.argv = [str(ROOT / "orchestrator.py"), "snipe", "10000"]
            runpy.run_path(str(ROOT / "orchestrator.py"), run_name="__main__")
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)
            try:
                sys.path.remove(str(ROOT))
            except ValueError:
                pass

        queue_path = Path(td) / "data" / "pending_execution_queue.json"
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        batches = data.get("batches") or []
        assert client_cls.submit_count == 0, "HITL sniper submitted a broker order"
        assert len(batches) == 1, data
        trades = batches[0].get("trades") or []
        assert len(trades) == 1, data
        assert trades[0]["ticker"] == "SPY" and trades[0]["trade_type"] == "STOCK", trades

    print("[smoke] smoke_snipe_hitl_queue: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
