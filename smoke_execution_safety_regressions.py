#!/usr/bin/env python3
"""
Smoke: high-severity execution safety regressions stay fixed.

Covered:
- OPTION buys enforce notional caps before broker submit.
- OPTION orders are refreshed before deciding whether to persist positions.
- execute_pending keeps failed trades queued for operator retry.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path


def _module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, val in attrs.items():
        setattr(mod, key, val)
    sys.modules[name] = mod
    return mod


def _install_orchestrator_import_stubs() -> None:
    dotenv_mod = _module("dotenv", load_dotenv=lambda *args, **kwargs: None)
    dateutil_pkg = _module("dateutil")
    dateutil_pkg.__path__ = []

    def parse_date(value):
        text = str(value)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.strptime(text, "%Y-%m-%d")

    _module("dateutil.parser", parse=parse_date)
    _module("pytz", UTC=timezone.utc, timezone=lambda name: timezone.utc)

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
        scan_intraday_opportunities=lambda portfolio_value: [],
        evaluate_quick_entry=lambda *args, **kwargs: {},
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

    class TradingClient:
        def __init__(self, *args, **kwargs):
            pass

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


class _Order:
    def __init__(self, order_id: str, status: str, filled_qty=None, filled_avg_price=None):
        self.id = order_id
        self.status = status
        self.filled_qty = filled_qty
        self.filled_avg_price = filled_avg_price


class _FakeAlpacaClient:
    def __init__(self, refreshed_order: _Order | None = None):
        self.submit_count = 0
        self.refresh_count = 0
        self.refreshed_order = refreshed_order

    def submit_order(self, order_data):
        self.submit_count += 1
        return _Order("option_order_1", "accepted")

    def get_order_by_id(self, order_id):
        self.refresh_count += 1
        return self.refreshed_order or _Order(order_id, "accepted")


def _preserve_halt_file():
    path = Path("data/operator_trading_halt.json")
    existed = path.exists()
    original = path.read_text(encoding="utf-8") if existed else None
    return path, existed, original


def main() -> int:
    os.environ.pop("ALPACA_API_KEY", None)
    os.environ.pop("ALPACA_SECRET_KEY", None)
    os.environ.pop("FORTRESS_TRADING_HALT", None)
    os.environ["ALPACA_BASE_URL"] = "https://paper-api.alpaca.markets"
    _install_orchestrator_import_stubs()

    halt_path, halt_existed, halt_original = _preserve_halt_file()
    try:
        from utils.operator_halt import set_trading_halt

        set_trading_halt(False, reason="smoke_execution_safety_regressions", actor="smoke")
        import orchestrator as orch

        added_positions: list[dict] = []
        orch.add_position = lambda pos: added_positions.append(pos)
        params = {"stop_loss_pct": -2.0, "take_profit_pct": 15.0}
        trade = {
            "trade_type": "OPTION",
            "ticker": "SPY",
            "strike": 500,
            "expiration": "2026-12-18",
            "contracts": 100,
            "entry_price": 50.0,
            "call": True,
        }

        os.environ["FORTRESS_MAX_ORDER_NOTIONAL_USD"] = "25000"
        blocked_client = _FakeAlpacaClient()
        orch.alpaca_client = blocked_client
        status, blocked_trade = asyncio.run(orch.submit_approved_screening_trade(dict(trade), [], params))
        assert status == "failure", blocked_trade
        assert blocked_client.submit_count == 0, "notional-capped option should not reach broker submit"
        assert "notional" in (blocked_trade.get("execution_error") or ""), blocked_trade

        os.environ["FORTRESS_MAX_ORDER_NOTIONAL_USD"] = "1000000"
        filled_client = _FakeAlpacaClient(_Order("option_order_1", "filled", filled_qty=2, filled_avg_price=4.2))
        orch.alpaca_client = filled_client
        filled_trade = dict(trade)
        filled_trade["contracts"] = 2
        filled_trade["entry_price"] = 4.0
        status, _ = asyncio.run(orch.submit_approved_screening_trade(filled_trade, [], params))
        assert status == "success", "filled option order should be persisted after refresh"
        assert filled_client.refresh_count >= 1, "option order status must be refreshed before fill decision"
        assert len(added_positions) == 1, added_positions
        assert added_positions[0]["ticker"].startswith("SPY"), added_positions[0]

        with tempfile.TemporaryDirectory() as td:
            orch.DATA_DIR = Path(td) / "data"
            from utils.pending_execution_queue import append_pending_batch, load_batches

            append_pending_batch(
                source="smoke",
                run_id="pending_safety",
                candidates=[],
                trades=[{"ticker": "OK"}, {"ticker": "FAIL"}],
                data_dir=orch.DATA_DIR,
            )

            async def fake_submit(pending_trade, candidates, current_params):
                if pending_trade["ticker"] == "OK":
                    return "success", pending_trade
                updated = dict(pending_trade)
                updated["execution_error"] = "mock broker failure"
                return "failure", updated

            orch.submit_approved_screening_trade = fake_submit
            result = orch.flush_pending_execution_queue()
            assert result["executed"] == 1 and result["failed"] == 1, result
            remaining = load_batches(orch.DATA_DIR)
            assert len(remaining) == 1, remaining
            assert [t["ticker"] for t in remaining[0]["trades"]] == ["FAIL"], remaining

        print("[smoke] smoke_execution_safety_regressions: PASS")
        return 0
    finally:
        os.environ.pop("FORTRESS_MAX_ORDER_NOTIONAL_USD", None)
        if halt_existed:
            halt_path.parent.mkdir(parents=True, exist_ok=True)
            halt_path.write_text(halt_original or "", encoding="utf-8")
        else:
            try:
                halt_path.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
