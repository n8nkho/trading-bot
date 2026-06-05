#!/usr/bin/env python3
"""Smoke: intraday sniper queues approved entries in HITL mode without broker submission."""

from __future__ import annotations

import json
import os
import runpy
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


class _Request:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _Enum:
    BUY = "buy"
    SELL = "sell"
    DAY = "day"
    CLOSED = "closed"


class _Account:
    buying_power = "100000"
    equity = "100000"
    cash = "100000"
    portfolio_value = "100000"


class _TradingClient:
    submit_count = 0

    def __init__(self, *_args, **_kwargs):
        pass

    def get_account(self):
        return _Account()

    def get_all_positions(self):
        return []

    def submit_order(self, _order_data):
        type(self).submit_count += 1
        return types.SimpleNamespace(
            id="unexpected-order",
            filled_qty="1",
            filled_avg_price="100",
            status="filled",
        )


def _install_stubs() -> None:
    _stub_module("dotenv", load_dotenv=lambda *_args, **_kwargs: None)
    _stub_module("pytz")
    _stub_module("dateutil")
    _stub_module("dateutil.parser", parse=lambda _value: datetime.now(timezone.utc))

    _stub_module("alpaca")
    _stub_module("alpaca.trading")
    _stub_module("alpaca.trading.client", TradingClient=_TradingClient)
    _stub_module(
        "alpaca.trading.requests",
        MarketOrderRequest=_Request,
        GetOrdersRequest=_Request,
    )
    _stub_module(
        "alpaca.trading.enums",
        OrderSide=_Enum,
        TimeInForce=_Enum,
        QueryOrderStatus=_Enum,
    )

    _stub_module("agents.screener_agent", run_screener=lambda *_args, **_kwargs: [])
    _stub_module("agents.entry_agent", evaluate_entry=lambda *_args, **_kwargs: {})
    _stub_module("agents.exit_monitor", monitor_positions=lambda *_args, **_kwargs: [])
    _stub_module(
        "agents.risk_guardian",
        check_risk_limits=lambda *_args, **_kwargs: {"approved": True},
        get_risk_limits=lambda **_kwargs: {"max_positions": 5},
        get_risk_status=lambda: {"consecutive_losses": 0, "circuit_breaker_active": False},
        update_consecutive_losses=lambda *_args, **_kwargs: None,
    )
    _stub_module(
        "agents.performance_analyzer",
        track_decision=lambda *_args, **_kwargs: None,
        load_current_params=lambda: {"stop_loss_pct": -0.02, "take_profit_pct": 0.05},
    )
    _stub_module(
        "agents.llama_watchdog",
        run_watchdog=lambda *_args, **_kwargs: None,
        preload_models=lambda *_args, **_kwargs: None,
        is_emergency_mode=lambda: False,
    )
    _stub_module("agents.document_analyst", quick_fundamental_check=lambda *_args, **_kwargs: {})
    _stub_module(
        "agents.intraday_sniper",
        scan_intraday_opportunities=lambda _portfolio_value: [
            {"ticker": "AAPL", "entry_price": 100.0, "metrics": {"rsi": 22}}
        ],
        evaluate_quick_entry=lambda *_args, **_kwargs: {
            "action": "BUY",
            "shares": 2,
            "position_value": 200.0,
            "confidence": 0.91,
        },
    )

    _stub_module("utils.grok_sentiment", check_twitter_sentiment=lambda *_args, **_kwargs: {})
    _stub_module("utils.option_contract_schema", normalize_option_decision=lambda decision: decision)
    _stub_module("utils.policy_profile", get_profile_bundle=lambda: {"execution": {"sniper_max_trades_per_run": 1}})
    _stub_module("utils.trust_ledger", append_trust_event=lambda *_args, **_kwargs: None)
    _stub_module(
        "utils.run_registry",
        log_screening_completed=lambda *_args, **_kwargs: None,
        log_screening_failed=lambda *_args, **_kwargs: None,
        log_screening_started=lambda *_args, **_kwargs: "smoke-run",
    )
    _stub_module(
        "utils.pre_trade_gate",
        evaluate_pre_trade_submission=lambda **_kwargs: {"allowed": True, "reasons": []},
        format_gate_block_message=lambda gate: str(gate),
    )
    _stub_module(
        "utils.cost_calculator",
        get_daily_costs=lambda: {},
        get_monthly_projection=lambda: {},
        get_lifetime_costs=lambda: {},
        get_cost_per_trade=lambda: 0,
        generate_cost_report=lambda: {},
    )
    _stub_module(
        "utils.execution_mode",
        get_execution_mode=lambda: os.getenv("FORTRESS_EXECUTION_MODE", "autonomous"),
    )


def main() -> int:
    _install_stubs()
    os.environ["FORTRESS_EXECUTION_MODE"] = "human_in_loop"
    os.environ["ALPACA_API_KEY"] = "DUMMY"
    os.environ["ALPACA_SECRET_KEY"] = "DUMMY"
    os.environ["ALPACA_BASE_URL"] = "https://paper-api.alpaca.markets"
    sys.path.insert(0, str(ROOT))

    old_argv = sys.argv[:]
    old_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="snipe-hitl-") as td:
        os.chdir(td)
        try:
            sys.argv = [str(ROOT / "orchestrator.py"), "snipe", "10000"]
            runpy.run_path(str(ROOT / "orchestrator.py"), run_name="__main__")
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)

        queue_path = Path(td) / "data" / "pending_execution_queue.json"
        assert queue_path.exists(), "HITL sniper did not create pending queue"
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        batches = data.get("batches") or []
        assert len(batches) == 1, data
        assert batches[0].get("source") == "intraday_sniper", batches[0]
        trades = batches[0].get("trades") or []
        assert len(trades) == 1, batches[0]
        assert trades[0]["ticker"] == "AAPL", trades[0]
        assert trades[0]["shares"] == 2, trades[0]

        positions_path = Path(td) / "data" / "positions.json"
        assert not positions_path.exists(), "HITL sniper should not persist filled positions"
        assert _TradingClient.submit_count == 0, "HITL sniper submitted a broker order"

    print("[OK] smoke_snipe_hitl_queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
