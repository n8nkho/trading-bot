#!/usr/bin/env python3
"""Smoke: intraday sniper HITL queues approved trades without broker submission."""
from __future__ import annotations

import os
import runpy
import shutil
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path


def _stub_module(name: str, **attrs) -> None:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod


def _install_stubs() -> None:
    parser = types.ModuleType("dateutil.parser")
    parser.parse = lambda value: datetime.fromisoformat(str(value))
    dateutil = types.ModuleType("dateutil")
    dateutil.parser = parser
    sys.modules["dateutil"] = dateutil
    sys.modules["dateutil.parser"] = parser
    _stub_module("pytz", timezone=lambda *a, **k: None)
    _stub_module("dotenv", load_dotenv=lambda *a, **k: None)

    alpaca = types.ModuleType("alpaca")
    trading = types.ModuleType("alpaca.trading")
    client = types.ModuleType("alpaca.trading.client")
    requests = types.ModuleType("alpaca.trading.requests")
    enums = types.ModuleType("alpaca.trading.enums")

    class _Account:
        buying_power = "100000"
        equity = "100000"
        cash = "100000"
        portfolio_value = "100000"

    class _TradingClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_account(self):
            return _Account()

        def get_all_positions(self):
            return []

    class _Request:
        def __init__(self, *args, **kwargs):
            pass

    client.TradingClient = _TradingClient
    requests.MarketOrderRequest = _Request
    requests.GetOrdersRequest = _Request
    enums.OrderSide = types.SimpleNamespace(BUY="buy", SELL="sell")
    enums.TimeInForce = types.SimpleNamespace(DAY="day")
    enums.QueryOrderStatus = types.SimpleNamespace(CLOSED="closed", OPEN="open")
    sys.modules["alpaca"] = alpaca
    sys.modules["alpaca.trading"] = trading
    sys.modules["alpaca.trading.client"] = client
    sys.modules["alpaca.trading.requests"] = requests
    sys.modules["alpaca.trading.enums"] = enums

    _stub_module("agents.screener_agent", run_screener=lambda *a, **k: [])
    _stub_module("agents.entry_agent", evaluate_entry=lambda *a, **k: [])
    _stub_module("agents.exit_monitor", monitor_positions=lambda *a, **k: [])
    _stub_module(
        "agents.risk_guardian",
        check_risk_limits=lambda *a, **k: {"approved": True},
        get_risk_limits=lambda *a, **k: {"max_positions": 5},
        get_risk_status=lambda *a, **k: {},
        update_consecutive_losses=lambda *a, **k: None,
    )
    _stub_module(
        "agents.performance_analyzer",
        track_decision=lambda *a, **k: None,
        load_current_params=lambda *a, **k: {"stop_loss_pct": -0.02, "take_profit_pct": 0.05},
    )
    _stub_module(
        "agents.llama_watchdog",
        run_watchdog=lambda *a, **k: None,
        preload_models=lambda *a, **k: None,
        is_emergency_mode=lambda *a, **k: False,
    )
    _stub_module("agents.document_analyst", quick_fundamental_check=lambda *a, **k: None)
    _stub_module(
        "agents.intraday_sniper",
        scan_intraday_opportunities=lambda *a, **k: [{"ticker": "AAPL", "entry_price": 100.0, "metrics": {}}],
        evaluate_quick_entry=lambda *a, **k: {"action": "BUY", "shares": 2, "position_value": 200.0},
    )
    _stub_module("utils.grok_sentiment", check_twitter_sentiment=lambda *a, **k: None)
    _stub_module("utils.option_contract_schema", normalize_option_decision=lambda x: x)
    _stub_module("utils.policy_profile", get_profile_bundle=lambda *a, **k: {"active_profile": "balanced", "risk": {}, "execution": {"sniper_max_trades_per_run": 3}})
    _stub_module("utils.trust_ledger", append_trust_event=lambda *a, **k: None)
    _stub_module(
        "utils.run_registry",
        log_screening_completed=lambda *a, **k: None,
        log_screening_failed=lambda *a, **k: None,
        log_screening_started=lambda *a, **k: None,
    )
    _stub_module(
        "utils.pre_trade_gate",
        evaluate_pre_trade_submission=lambda *a, **k: (_ for _ in ()).throw(AssertionError("broker submission attempted in HITL mode")),
        format_gate_block_message=lambda gate: "blocked",
    )
    _stub_module(
        "utils.cost_calculator",
        get_daily_costs=lambda *a, **k: {},
        get_monthly_projection=lambda *a, **k: {},
        get_lifetime_costs=lambda *a, **k: {},
        get_cost_per_trade=lambda *a, **k: {},
        generate_cost_report=lambda *a, **k: {},
    )
    _stub_module("utils.execution_mode", get_execution_mode=lambda *a, **k: "human_in_loop")


def main() -> int:
    td = Path(tempfile.mkdtemp())
    old_cwd = Path.cwd()
    old_argv = sys.argv[:]
    try:
        _install_stubs()
        os.environ["ALPACA_BASE_URL"] = "https://paper-api.alpaca.markets"
        os.environ["ALPACA_API_KEY"] = "DUMMY"
        os.environ["ALPACA_SECRET_KEY"] = "DUMMY"
        sys.path.insert(0, "/workspace")
        os.chdir(td)
        sys.argv = ["orchestrator.py", "snipe", "10000"]
        runpy.run_module("orchestrator", run_name="__main__")

        from utils.pending_execution_queue import load_batches

        batches = load_batches(td / "data")
        trades = [t for b in batches for t in b.get("trades", [])]
        assert len(trades) == 1, batches
        assert trades[0]["ticker"] == "AAPL", trades
        assert trades[0]["shares"] == 2, trades
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
        shutil.rmtree(td, ignore_errors=True)

    print("[OK] smoke_snipe_hitl_queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
