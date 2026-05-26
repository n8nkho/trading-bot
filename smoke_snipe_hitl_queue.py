#!/usr/bin/env python3
"""
Smoke: intraday sniper must queue in human-in-the-loop mode without broker submission.
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


def _install_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


class _FakeTradingClient:
    submit_called = 0

    def __init__(self, *args, **kwargs):
        pass

    def get_account(self):
        return types.SimpleNamespace(
            buying_power="1000000",
            equity="10000",
            cash="1000000",
            portfolio_value="10000",
        )

    def get_all_positions(self):
        return []

    def submit_order(self, order_data):
        _FakeTradingClient.submit_called += 1
        raise RuntimeError("broker submission should not be called in HITL sniper mode")


class _OrderRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _install_dependency_stubs() -> None:
    parser_mod = _install_module("dateutil.parser")
    _install_module("dateutil", parser=parser_mod)
    _install_module("pytz", timezone=lambda name: None)
    _install_module("dotenv", load_dotenv=lambda *args, **kwargs: None)

    _install_module("alpaca")
    _install_module("alpaca.trading")
    _install_module("alpaca.trading.client", TradingClient=_FakeTradingClient)
    _install_module(
        "alpaca.trading.requests",
        MarketOrderRequest=_OrderRequest,
        GetOrdersRequest=_OrderRequest,
    )
    _install_module(
        "alpaca.trading.enums",
        OrderSide=types.SimpleNamespace(BUY="buy", SELL="sell"),
        TimeInForce=types.SimpleNamespace(DAY="day"),
        QueryOrderStatus=types.SimpleNamespace(CLOSED="closed", OPEN="open"),
    )

    _install_module("agents.screener_agent", run_screener=lambda: [])
    _install_module("agents.entry_agent", evaluate_entry=lambda candidates, portfolio_value: [])
    _install_module("agents.exit_monitor", monitor_positions=lambda *args, **kwargs: {})
    _install_module(
        "agents.risk_guardian",
        check_risk_limits=lambda portfolio_data, new_position, strict_mode=False: {"approved": True},
        get_risk_limits=lambda: {},
        get_risk_status=lambda: {"consecutive_losses": 0, "circuit_breaker_active": False},
        update_consecutive_losses=lambda *args, **kwargs: None,
    )
    _install_module(
        "agents.performance_analyzer",
        track_decision=lambda *args, **kwargs: None,
        load_current_params=lambda: {"stop_loss_pct": -2.0, "take_profit_pct": 15.0},
    )
    _install_module(
        "agents.llama_watchdog",
        run_watchdog=lambda *args, **kwargs: {},
        preload_models=lambda *args, **kwargs: {},
        is_emergency_mode=lambda: False,
    )
    _install_module("agents.document_analyst", quick_fundamental_check=lambda *args, **kwargs: {})
    _install_module(
        "agents.intraday_sniper",
        scan_intraday_opportunities=lambda portfolio_value: [
            {"ticker": "AAPL", "entry_price": 100.0, "metrics": {"volume_ratio": 2.0}}
        ],
        evaluate_quick_entry=lambda ticker, entry_price, metrics, portfolio_value=0: {
            "ticker": ticker,
            "action": "BUY",
            "reason": "smoke sniper buy",
            "shares": 1,
            "entry_price": entry_price,
            "position_value": entry_price,
            "confidence": 0.99,
            "trade_type": "STOCK",
        },
    )

    _install_module("utils.grok_sentiment", check_twitter_sentiment=lambda *args, **kwargs: {})
    _install_module("utils.option_contract_schema", normalize_option_decision=lambda x: x)
    _install_module(
        "utils.policy_profile",
        get_profile_bundle=lambda: {"active_profile": "smoke", "execution": {"sniper_max_trades_per_run": 3}},
    )
    _install_module("utils.trust_ledger", append_trust_event=lambda *args, **kwargs: None)
    _install_module(
        "utils.run_registry",
        log_screening_completed=lambda *args, **kwargs: None,
        log_screening_failed=lambda *args, **kwargs: None,
        log_screening_started=lambda *args, **kwargs: "smoke_run",
    )
    _install_module(
        "utils.pre_trade_gate",
        evaluate_pre_trade_submission=lambda *args, **kwargs: {"allowed": True, "reasons": []},
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
    _install_module("utils.execution_mode", get_execution_mode=lambda: "human_in_loop")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    _install_dependency_stubs()
    sys.modules.pop("orchestrator", None)

    old_argv = sys.argv[:]
    old_cwd = Path.cwd()
    old_env = os.environ.copy()
    try:
        os.environ["ALPACA_API_KEY"] = "DUMMY"
        os.environ["ALPACA_SECRET_KEY"] = "DUMMY"
        os.environ["ALPACA_BASE_URL"] = "https://paper-api.alpaca.markets"
        sys.argv = ["orchestrator.py", "snipe", "10000"]
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            try:
                runpy.run_path(str(ROOT / "orchestrator.py"), run_name="__main__")
            except SystemExit as e:
                if e.code not in (0, None):
                    raise
            queue_path = Path(td) / "data" / "pending_execution_queue.json"
            data = json.loads(queue_path.read_text(encoding="utf-8"))
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)

    assert _FakeTradingClient.submit_called == 0, "HITL sniper submitted to broker instead of queueing"
    batches = data.get("batches") or []
    assert len(batches) == 1, data
    batch = batches[0]
    assert batch.get("source") == "intraday_sniper", batch
    trades = batch.get("trades") or []
    assert len(trades) == 1, batch
    assert trades[0].get("ticker") == "AAPL", trades
    assert trades[0].get("shares") == 1, trades

    print("[OK] smoke_snipe_hitl_queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
