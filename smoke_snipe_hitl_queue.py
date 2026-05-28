#!/usr/bin/env python3
"""Regression: intraday sniper queues HITL trades without broker submission."""

from __future__ import annotations

import json
import os
import runpy
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _install_module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _install_stubs(submit_calls: list[dict]) -> None:
    _install_module("dotenv", load_dotenv=lambda *a, **k: None)

    dateutil_mod = _install_module("dateutil")
    parser_mod = _install_module("dateutil.parser", parse=lambda value: __import__("datetime").datetime.fromisoformat(value))
    dateutil_mod.parser = parser_mod

    _install_module("pytz", timezone=lambda _name: None)

    alpaca_mod = _install_module("alpaca")
    trading_mod = _install_module("alpaca.trading")
    alpaca_mod.trading = trading_mod

    class _Order:
        id = "paper-order-1"
        filled_qty = "1"
        filled_avg_price = "100"
        status = "filled"

    class _Account:
        buying_power = "100000"
        equity = "100000"
        cash = "100000"
        portfolio_value = "100000"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def get_account(self):
            return _Account()

        def get_all_positions(self):
            return []

        def submit_order(self, order_data):
            submit_calls.append(getattr(order_data, "kwargs", {}))
            return _Order()

    client_mod = _install_module("alpaca.trading.client", TradingClient=_Client)
    trading_mod.client = client_mod

    class _Request:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    requests_mod = _install_module(
        "alpaca.trading.requests",
        MarketOrderRequest=_Request,
        GetOrdersRequest=_Request,
    )
    trading_mod.requests = requests_mod
    enums_mod = _install_module(
        "alpaca.trading.enums",
        OrderSide=types.SimpleNamespace(BUY="buy", SELL="sell"),
        TimeInForce=types.SimpleNamespace(DAY="day"),
        QueryOrderStatus=types.SimpleNamespace(CLOSED="closed", OPEN="open"),
    )
    trading_mod.enums = enums_mod

    _install_module("agents.screener_agent", run_screener=lambda: [])
    _install_module("agents.entry_agent", evaluate_entry=lambda *a, **k: {})
    _install_module("agents.exit_monitor", monitor_positions=lambda *a, **k: [])
    _install_module(
        "agents.risk_guardian",
        check_risk_limits=lambda *a, **k: {"approved": True, "reason": "ok"},
        get_risk_limits=lambda *a, **k: {"max_positions": 5},
        get_risk_status=lambda: {"consecutive_losses": 0, "circuit_breaker_active": False},
        update_consecutive_losses=lambda *a, **k: None,
    )
    _install_module("agents.performance_analyzer", track_decision=lambda *a, **k: None, load_current_params=lambda: {"stop_loss_pct": -0.02})
    _install_module("agents.llama_watchdog", run_watchdog=lambda: {}, preload_models=lambda: None, is_emergency_mode=lambda: False)
    _install_module("agents.document_analyst", quick_fundamental_check=lambda *a, **k: {})
    _install_module(
        "agents.intraday_sniper",
        scan_intraday_opportunities=lambda _portfolio_value: [
            {"ticker": "AAPL", "entry_price": 100.0, "metrics": {"rsi": 30}}
        ],
        evaluate_quick_entry=lambda ticker, entry_price, metrics, portfolio_value: {
            "ticker": ticker,
            "action": "BUY",
            "shares": 1,
            "entry_price": entry_price,
            "position_value": entry_price,
            "confidence": 0.95,
            "reason": "smoke",
        },
    )
    _install_module("utils.grok_sentiment", check_twitter_sentiment=lambda *a, **k: {})
    _install_module("utils.option_contract_schema", normalize_option_decision=lambda decision: decision)
    _install_module(
        "utils.policy_profile",
        get_profile_bundle=lambda *a, **k: {
            "active_profile": "balanced",
            "risk": {},
            "execution": {"sniper_max_trades_per_run": 3},
        },
    )
    _install_module("utils.trust_ledger", append_trust_event=lambda *a, **k: None)
    _install_module(
        "utils.run_registry",
        log_screening_completed=lambda *a, **k: None,
        log_screening_failed=lambda *a, **k: None,
        log_screening_started=lambda *a, **k: None,
    )
    _install_module(
        "utils.pre_trade_gate",
        evaluate_pre_trade_submission=lambda *a, **k: {"allowed": True},
        format_gate_block_message=lambda gate: "blocked",
    )
    _install_module(
        "utils.cost_calculator",
        get_daily_costs=lambda: {},
        get_monthly_projection=lambda: {},
        get_lifetime_costs=lambda: {},
        get_cost_per_trade=lambda: 0,
        generate_cost_report=lambda: {},
    )


def main() -> int:
    submit_calls: list[dict] = []
    _install_stubs(submit_calls)

    env_before = os.environ.copy()
    argv_before = sys.argv[:]
    cwd_before = Path.cwd()

    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        os.environ.update(
            {
                "ALPACA_API_KEY": "paper-key-12345",
                "ALPACA_SECRET_KEY": "paper-secret-12345",
                "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
                "FORTRESS_EXECUTION_MODE": "human_in_loop",
            }
        )
        sys.argv = [str(ROOT / "orchestrator.py"), "snipe", "10000"]
        try:
            runpy.run_path(str(ROOT / "orchestrator.py"), run_name="__main__")
        finally:
            sys.argv = argv_before
            os.environ.clear()
            os.environ.update(env_before)
            os.chdir(cwd_before)

        queue_path = Path(tmp) / "data" / "pending_execution_queue.json"
        assert queue_path.exists(), "HITL snipe did not write pending queue"
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        batches = data.get("batches") or []
        assert len(batches) == 1, data
        assert batches[0]["source"] == "intraday_sniper", data
        trades = batches[0].get("trades") or []
        assert len(trades) == 1 and trades[0]["ticker"] == "AAPL", data
        assert submit_calls == [], f"broker submit was called in HITL mode: {submit_calls}"

    print("PASS: snipe HITL queues approved trade without broker submission")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
