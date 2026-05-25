#!/usr/bin/env python3
"""Smoke tests for high-impact orchestrator execution safety gates."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path


def _install_import_stubs() -> None:
    """Let this focused smoke import orchestrator without optional runtime deps."""
    if "dateutil" not in sys.modules:
        dateutil_mod = types.ModuleType("dateutil")
        parser_mod = types.ModuleType("dateutil.parser")
        parser_mod.parse = lambda value: datetime.fromisoformat(str(value))
        dateutil_mod.parser = parser_mod
        sys.modules["dateutil"] = dateutil_mod
        sys.modules["dateutil.parser"] = parser_mod

    if "pytz" not in sys.modules:
        pytz_mod = types.ModuleType("pytz")
        pytz_mod.timezone = lambda name: None
        sys.modules["pytz"] = pytz_mod

    if "dotenv" not in sys.modules:
        dotenv_mod = types.ModuleType("dotenv")
        dotenv_mod.load_dotenv = lambda *args, **kwargs: None
        sys.modules["dotenv"] = dotenv_mod

    if "alpaca.trading.client" not in sys.modules:
        alpaca_mod = types.ModuleType("alpaca")
        trading_mod = types.ModuleType("alpaca.trading")
        client_mod = types.ModuleType("alpaca.trading.client")
        requests_mod = types.ModuleType("alpaca.trading.requests")
        enums_mod = types.ModuleType("alpaca.trading.enums")

        class DummyTradingClient:
            def __init__(self, *args, **kwargs):
                pass

            def get_all_positions(self):
                return []

        class DummyRequest:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class DummyOrderSide:
            BUY = "buy"
            SELL = "sell"

        class DummyTimeInForce:
            DAY = "day"

        class DummyQueryOrderStatus:
            CLOSED = "closed"

        client_mod.TradingClient = DummyTradingClient
        requests_mod.MarketOrderRequest = DummyRequest
        requests_mod.GetOrdersRequest = DummyRequest
        enums_mod.OrderSide = DummyOrderSide
        enums_mod.TimeInForce = DummyTimeInForce
        enums_mod.QueryOrderStatus = DummyQueryOrderStatus
        sys.modules["alpaca"] = alpaca_mod
        sys.modules["alpaca.trading"] = trading_mod
        sys.modules["alpaca.trading.client"] = client_mod
        sys.modules["alpaca.trading.requests"] = requests_mod
        sys.modules["alpaca.trading.enums"] = enums_mod

    stubs = {
        "agents.screener_agent": {"run_screener": lambda: []},
        "agents.entry_agent": {"evaluate_entry": lambda candidates, portfolio_value: []},
        "agents.exit_monitor": {"monitor_positions": lambda positions: []},
        "agents.risk_guardian": {
            "check_risk_limits": lambda portfolio_data, new_position, strict_mode=False: {
                "approved": True,
                "reason": "stub",
            },
            "get_risk_limits": lambda strict_mode=False: {"max_positions": 5},
            "get_risk_status": lambda: {"consecutive_losses": 0, "circuit_breaker_active": False},
            "update_consecutive_losses": lambda trade: None,
        },
        "agents.performance_analyzer": {
            "track_decision": lambda *args, **kwargs: None,
            "load_current_params": lambda: {"stop_loss_pct": -2.0, "take_profit_pct": 15.0},
        },
        "agents.llama_watchdog": {
            "run_watchdog": lambda: None,
            "preload_models": lambda: None,
            "is_emergency_mode": lambda: False,
        },
        "agents.document_analyst": {"quick_fundamental_check": lambda ticker, confidence: None},
        "agents.intraday_sniper": {
            "scan_intraday_opportunities": lambda portfolio_value: [],
            "evaluate_quick_entry": lambda ticker, entry_price, metrics, portfolio_value: {"action": "SKIP"},
        },
        "utils.grok_sentiment": {"check_twitter_sentiment": lambda ticker, confidence: None},
        "utils.option_contract_schema": {"normalize_option_decision": lambda decision: dict(decision)},
        "utils.policy_profile": {
            "get_profile_bundle": lambda: {"active_profile": "smoke", "execution": {}, "risk": {}}
        },
        "utils.trust_ledger": {"append_trust_event": lambda *args, **kwargs: None},
        "utils.run_registry": {
            "log_screening_completed": lambda *args, **kwargs: None,
            "log_screening_failed": lambda *args, **kwargs: None,
            "log_screening_started": lambda *args, **kwargs: None,
        },
        "utils.pre_trade_gate": {
            "evaluate_pre_trade_submission": lambda *args, **kwargs: {"allowed": True, "reasons": []},
            "format_gate_block_message": lambda gate: "blocked",
        },
        "utils.cost_calculator": {
            "get_daily_costs": lambda: {},
            "get_monthly_projection": lambda: {},
            "get_lifetime_costs": lambda: {},
            "get_cost_per_trade": lambda: {},
            "generate_cost_report": lambda: {},
        },
        "utils.execution_mode": {"get_execution_mode": lambda: "autonomous"},
    }

    for module_name, attrs in stubs.items():
        if module_name in sys.modules:
            continue
        mod = types.ModuleType(module_name)
        for name, value in attrs.items():
            setattr(mod, name, value)
        sys.modules[module_name] = mod


def _import_orchestrator():
    os.environ.setdefault("APCA_API_KEY_ID", "smoke_dummy_key")
    os.environ.setdefault("APCA_API_SECRET_KEY", "smoke_dummy_secret")
    _install_import_stubs()
    import orchestrator as orch

    orch.append_trust_event = lambda *args, **kwargs: None
    return orch


def test_position_updates_are_serialized(orch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        orch.DATA_DIR = data_dir
        orch.POSITIONS_FILE = data_dir / "positions.json"

        def add_one(i: int) -> None:
            orch.add_position(
                {
                    "ticker": f"T{i}",
                    "shares": 1,
                    "entry_price": 100.0,
                    "entry_date": "2026-01-01T00:00:00",
                }
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add_one, range(25)))

        positions = json.loads(orch.POSITIONS_FILE.read_text(encoding="utf-8"))
        assert len(positions) == 25, f"lost position update(s): {len(positions)}"
        assert {p["ticker"] for p in positions} == {f"T{i}" for i in range(25)}


def test_execute_pending_rechecks_strict_hedge_gate(orch) -> None:
    from utils.pending_execution_queue import append_pending_batch

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        orch.DATA_DIR = data_dir
        orch.POSITIONS_FILE = data_dir / "positions.json"

        trade = {
            "ticker": "AAPL",
            "action": "BUY",
            "trade_type": "STOCK",
            "shares": 1,
            "entry_price": 100.0,
            "position_size": 100.0,
            "confidence": 0.9,
        }
        append_pending_batch(
            source="daily_screening",
            run_id="smoke",
            candidates=[{"ticker": "AAPL", "sector": "Technology"}],
            trades=[trade],
            data_dir=data_dir,
        )

        submitted_orders = []
        orch.load_current_params = lambda: {"stop_loss_pct": -2.0, "take_profit_pct": 15.0}
        orch.get_risk_status = lambda: {"consecutive_losses": 2, "circuit_breaker_active": False}
        orch._load_latest_fortress_report = lambda max_age_hours=None: (
            None,
            {"path": None, "age_hours": None, "is_fresh": None},
        )
        orch.get_account_info = lambda: {
            "buying_power": 1_000_000.0,
            "equity": 10_000.0,
            "cash": 1_000_000.0,
            "portfolio_value": 10_000.0,
            "position_count": 0,
        }
        orch.check_risk_limits = lambda portfolio_data, new_position, strict_mode=False: {
            "approved": True,
            "reason": "mock ok",
        }

        def fake_execute_buy_order(ticker, shares, entry_price):
            submitted_orders.append((ticker, shares, entry_price))
            return {
                "success": True,
                "order_id": "should_not_submit",
                "filled_qty": shares,
                "filled_price": entry_price,
                "status": "filled",
                "error": None,
            }

        orch.execute_buy_order = fake_execute_buy_order

        result = orch.flush_pending_execution_queue()
        assert result["executed"] == 0, result
        assert result["failed"] == 1, result
        assert submitted_orders == [], submitted_orders


def main() -> int:
    orch = _import_orchestrator()
    test_position_updates_are_serialized(orch)
    test_execute_pending_rechecks_strict_hedge_gate(orch)
    print("[smoke] smoke_orchestrator_execution_safety: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
