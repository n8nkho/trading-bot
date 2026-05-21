#!/usr/bin/env python3
"""Smoke: HITL execute_pending keeps failed submissions queued for retry."""

from __future__ import annotations

import os
import runpy
import sys
import types
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory


DUMMY_SUBMITTED_ORDERS: list[object] = []


def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _install_import_stubs() -> None:
    """Stub import-time dependencies that this focused smoke does not exercise."""
    dateutil = _stub_module("dateutil")
    parser = _stub_module("dateutil.parser", parse=lambda value: datetime.fromisoformat(str(value)))
    dateutil.parser = parser

    _stub_module("pytz", UTC=timezone.utc)
    _stub_module("dotenv", load_dotenv=lambda *args, **kwargs: None)

    alpaca = _stub_module("alpaca")
    alpaca_trading = _stub_module("alpaca.trading")
    alpaca.trading = alpaca_trading

    class DummyTradingClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_account(self):
            return SimpleNamespace(
                buying_power="1000000",
                equity="100000",
                cash="1000000",
                portfolio_value="100000",
            )

        def get_all_positions(self):
            return []

        def submit_order(self, order_data):
            DUMMY_SUBMITTED_ORDERS.append(order_data)
            return SimpleNamespace(
                id="smoke_order",
                status="filled",
                filled_qty=1,
                filled_avg_price=10.0,
            )

    class DummyRequest:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    client_mod = _stub_module("alpaca.trading.client", TradingClient=DummyTradingClient)
    requests_mod = _stub_module(
        "alpaca.trading.requests",
        MarketOrderRequest=DummyRequest,
        GetOrdersRequest=DummyRequest,
    )
    enums_mod = _stub_module(
        "alpaca.trading.enums",
        OrderSide=SimpleNamespace(BUY="buy", SELL="sell"),
        TimeInForce=SimpleNamespace(DAY="day", GTC="gtc"),
        QueryOrderStatus=SimpleNamespace(CLOSED="closed", OPEN="open"),
    )
    alpaca_trading.client = client_mod
    alpaca_trading.requests = requests_mod
    alpaca_trading.enums = enums_mod

    agent_stubs = {
        "agents.screener_agent": {"run_screener": lambda: []},
        "agents.entry_agent": {"evaluate_entry": lambda *args, **kwargs: []},
        "agents.exit_monitor": {"monitor_positions": lambda *args, **kwargs: {}},
        "agents.risk_guardian": {
            "check_risk_limits": lambda *args, **kwargs: {"approved": True},
            "get_risk_limits": lambda *args, **kwargs: {},
            "get_risk_status": lambda *args, **kwargs: {},
            "update_consecutive_losses": lambda *args, **kwargs: None,
        },
        "agents.performance_analyzer": {
            "track_decision": lambda *args, **kwargs: None,
            "load_current_params": lambda: {"stop_loss_pct": -2.0, "take_profit_pct": 15.0},
        },
        "agents.llama_watchdog": {
            "run_watchdog": lambda *args, **kwargs: {},
            "preload_models": lambda *args, **kwargs: None,
            "is_emergency_mode": lambda *args, **kwargs: False,
        },
        "agents.document_analyst": {"quick_fundamental_check": lambda *args, **kwargs: {}},
        "agents.intraday_sniper": {
            "scan_intraday_opportunities": lambda *args, **kwargs: [],
            "evaluate_quick_entry": lambda *args, **kwargs: {},
        },
    }
    for name, attrs in agent_stubs.items():
        _stub_module(name, **attrs)

    util_stubs = {
        "utils.grok_sentiment": {"check_twitter_sentiment": lambda *args, **kwargs: {}},
        "utils.option_contract_schema": {"normalize_option_decision": lambda value: value},
        "utils.policy_profile": {"get_profile_bundle": lambda: {"execution": {}}},
        "utils.trust_ledger": {"append_trust_event": lambda *args, **kwargs: None},
        "utils.run_registry": {
            "log_screening_completed": lambda *args, **kwargs: None,
            "log_screening_failed": lambda *args, **kwargs: None,
            "log_screening_started": lambda *args, **kwargs: "smoke_run",
        },
        "utils.pre_trade_gate": {
            "evaluate_pre_trade_submission": lambda *args, **kwargs: {"allowed": True},
            "format_gate_block_message": lambda gate: "blocked",
        },
        "utils.cost_calculator": {
            "get_daily_costs": lambda *args, **kwargs: {},
            "get_monthly_projection": lambda *args, **kwargs: {},
            "get_lifetime_costs": lambda *args, **kwargs: {},
            "get_cost_per_trade": lambda *args, **kwargs: {},
            "generate_cost_report": lambda *args, **kwargs: {},
        },
    }
    for name, attrs in util_stubs.items():
        _stub_module(name, **attrs)


def _exercise_snipe_hitl(repo_root: Path) -> None:
    import agents.intraday_sniper as sniper
    import agents.risk_guardian as risk_guardian
    import utils.policy_profile as policy_profile

    DUMMY_SUBMITTED_ORDERS.clear()
    sniper.scan_intraday_opportunities = lambda portfolio_value: [
        {"ticker": "HITL", "entry_price": 10.0, "metrics": {"volume_ratio": 3.0}}
    ]
    sniper.evaluate_quick_entry = lambda ticker, entry_price, metrics, portfolio_value: {
        "ticker": ticker,
        "action": "BUY",
        "shares": 1,
        "position_value": entry_price,
        "confidence": 0.99,
        "reason": "smoke buy",
    }
    risk_guardian.check_risk_limits = lambda portfolio_data, new_position, strict_mode=False: {"approved": True}
    risk_guardian.get_risk_status = lambda: {"consecutive_losses": 0, "circuit_breaker_active": False}
    policy_profile.get_profile_bundle = lambda: {"execution": {"sniper_max_trades_per_run": 1}}

    old_argv = sys.argv[:]
    old_cwd = Path.cwd()
    saved_env = {
        key: os.environ.get(key)
        for key in (
            "FORTRESS_EXECUTION_MODE",
            "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY",
            "ALPACA_BASE_URL",
        )
    }

    with TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            os.environ["FORTRESS_EXECUTION_MODE"] = "human_in_loop"
            os.environ["ALPACA_API_KEY"] = "DUMMY"
            os.environ["ALPACA_SECRET_KEY"] = "DUMMY"
            os.environ["ALPACA_BASE_URL"] = "https://paper-api.alpaca.markets"
            sys.argv = ["orchestrator.py", "snipe", "10000"]
            try:
                runpy.run_path(str(repo_root / "orchestrator.py"), run_name="__main__")
            except SystemExit as exc:
                assert exc.code in (0, None), exc.code

            assert DUMMY_SUBMITTED_ORDERS == [], "snipe HITL must not submit broker orders"

            queue_path = Path(tmp) / "data" / "pending_execution_queue.json"
            queued = json.loads(queue_path.read_text(encoding="utf-8"))
            batches = queued["batches"]
            assert len(batches) == 1, queued
            assert batches[0]["source"] == "intraday_sniper", queued
            trades = batches[0]["trades"]
            assert len(trades) == 1, trades
            assert trades[0]["ticker"] == "HITL", trades
            assert trades[0]["shares"] == 1, trades
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def main() -> int:
    # Prevent import-time credential validation failures.
    os.environ.setdefault("APCA_API_KEY_ID", "DUMMY")
    os.environ.setdefault("APCA_API_SECRET_KEY", "DUMMY")
    os.environ.setdefault("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    _install_import_stubs()

    import orchestrator as orch
    from utils.pending_execution_queue import append_pending_batch, load_batches

    with TemporaryDirectory() as tmp:
        old_data_dir = orch.DATA_DIR
        orch.DATA_DIR = Path(tmp)
        try:
            append_pending_batch(
                source="daily_screening",
                run_id="smoke_hitl",
                candidates=[],
                trades=[
                    {"ticker": "OK", "shares": 1, "entry_price": 10.0},
                    {"ticker": "FAIL", "shares": 1, "entry_price": 20.0},
                ],
                data_dir=orch.DATA_DIR,
            )

            async def fake_submit(trade, candidates, current_params):
                processed = dict(trade)
                if processed["ticker"] == "OK":
                    processed["executed"] = True
                    return ("success", processed)
                processed["executed"] = False
                processed["execution_error"] = "simulated broker reject"
                return ("failure", processed)

            orch.submit_approved_screening_trade = fake_submit
            orch.load_current_params = lambda: {"stop_loss_pct": -2.0, "take_profit_pct": 15.0}
            orch.append_trust_event = lambda event, payload: None

            out = orch.flush_pending_execution_queue()
            assert out["executed"] == 1, out
            assert out["failed"] == 1, out
            assert out["retained_for_retry"] == 1, out

            batches = load_batches(orch.DATA_DIR)
            assert len(batches) == 1, batches
            retained = batches[0]["trades"]
            assert len(retained) == 1, retained
            assert retained[0]["ticker"] == "FAIL", retained
            assert retained[0]["execution_error"] == "simulated broker reject", retained
        finally:
            orch.DATA_DIR = old_data_dir

    _exercise_snipe_hitl(Path(__file__).resolve().parent)

    print("[OK] smoke_hitl_execution_queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
