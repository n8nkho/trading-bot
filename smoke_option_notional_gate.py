#!/usr/bin/env python3
"""Smoke: option BUYs enforce estimated notional before broker submission."""

from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timezone


def _install_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _install_import_stubs() -> None:
    parser_mod = _install_module(
        "dateutil.parser",
        parse=lambda value: datetime.fromisoformat(str(value).replace("Z", "+00:00")),
    )
    dateutil_mod = _install_module("dateutil", parser=parser_mod)
    dateutil_mod.parser = parser_mod
    _install_module("dotenv", load_dotenv=lambda *args, **kwargs: None)
    _install_module("pytz", timezone=lambda _name: timezone.utc)

    alpaca_mod = _install_module("alpaca")
    trading_mod = _install_module("alpaca.trading")
    client_mod = _install_module("alpaca.trading.client")
    requests_mod = _install_module("alpaca.trading.requests")
    enums_mod = _install_module("alpaca.trading.enums")
    alpaca_mod.trading = trading_mod
    trading_mod.client = client_mod
    trading_mod.requests = requests_mod
    trading_mod.enums = enums_mod

    class _TradingClient:
        def __init__(self, *args, **kwargs):
            pass

    class _Request:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _OrderSide:
        BUY = "buy"
        SELL = "sell"

    class _TimeInForce:
        DAY = "day"

    class _QueryOrderStatus:
        OPEN = "open"
        CLOSED = "closed"

    client_mod.TradingClient = _TradingClient
    requests_mod.MarketOrderRequest = _Request
    requests_mod.GetOrdersRequest = _Request
    enums_mod.OrderSide = _OrderSide
    enums_mod.TimeInForce = _TimeInForce
    enums_mod.QueryOrderStatus = _QueryOrderStatus

    _install_module("agents.screener_agent", run_screener=lambda: [])
    _install_module("agents.entry_agent", evaluate_entry=lambda *args, **kwargs: {})
    _install_module("agents.exit_monitor", monitor_positions=lambda *args, **kwargs: [])
    _install_module(
        "agents.risk_guardian",
        check_risk_limits=lambda *args, **kwargs: {"approved": True, "reason": "stub"},
        get_risk_limits=lambda: {},
        get_risk_status=lambda: {},
        update_consecutive_losses=lambda *args, **kwargs: None,
    )
    _install_module(
        "agents.performance_analyzer",
        track_decision=lambda *args, **kwargs: None,
        load_current_params=lambda: {"stop_loss_pct": -0.02, "take_profit_pct": 0.05},
    )
    _install_module(
        "agents.llama_watchdog",
        run_watchdog=lambda *args, **kwargs: None,
        preload_models=lambda *args, **kwargs: None,
        is_emergency_mode=lambda: False,
    )
    _install_module("agents.document_analyst", quick_fundamental_check=lambda *args, **kwargs: {})
    _install_module("agents.intraday_sniper", scan_intraday_opportunities=lambda *args, **kwargs: [], evaluate_quick_entry=lambda *args, **kwargs: {})
    _install_module("utils.grok_sentiment", check_twitter_sentiment=lambda *args, **kwargs: {})
    _install_module(
        "utils.cost_calculator",
        get_daily_costs=lambda: {},
        get_monthly_projection=lambda: {},
        get_lifetime_costs=lambda: {},
        get_cost_per_trade=lambda: {},
        generate_cost_report=lambda: {},
    )


class _FakeOrder:
    id = "fake-order"
    status = "accepted"
    filled_qty = None
    filled_avg_price = None


class _FakeTradingClient:
    def __init__(self):
        self.submitted = []

    def submit_order(self, order_data):
        self.submitted.append(order_data)
        return _FakeOrder()


def _option_trade(*, premium: float | None, contracts: int = 1, position_size: float | None = None) -> dict:
    trade = {
        "trade_type": "OPTION",
        "ticker": "SPY",
        "strike": 500,
        "expiration": "2026-12-18",
        "contracts": contracts,
        "call": True,
    }
    if premium is not None:
        trade["entry_price"] = premium
    if position_size is not None:
        trade["position_size"] = position_size
    return trade


def main() -> int:
    os.environ["APCA_API_KEY_ID"] = "DUMMY"
    os.environ["APCA_API_SECRET_KEY"] = "DUMMY"
    os.environ["ALPACA_BASE_URL"] = "https://paper-api.alpaca.markets"
    os.environ["FORTRESS_MAX_ORDER_NOTIONAL_USD"] = "1000"
    os.environ.pop("FORTRESS_TRADING_HALT", None)

    _install_import_stubs()

    import orchestrator
    from utils.operator_halt import set_trading_halt
    from utils.pre_trade_gate import evaluate_pre_trade_submission

    set_trading_halt(False, reason="smoke_option_notional_gate", actor="smoke")

    missing = evaluate_pre_trade_submission(
        side="BUY",
        symbol="SPY261218C00500000",
        qty=1,
        order_class="option",
        estimated_notional_usd=None,
    )
    assert not missing["allowed"], missing
    assert "missing_option_notional_estimate" in missing["reasons"], missing

    fake = _FakeTradingClient()
    orchestrator.alpaca_client = fake
    over_cap = _option_trade(premium=6.00, contracts=2)  # 2 * 6 * 100 = 1200 > cap
    status, blocked_trade = asyncio.run(
        orchestrator.submit_approved_screening_trade(
            over_cap,
            candidates=[],
            current_params={"stop_loss_pct": -0.02, "take_profit_pct": 0.05},
        )
    )
    assert status == "failure", (status, blocked_trade)
    assert fake.submitted == [], fake.submitted
    assert "estimated_notional_exceeds_cap" in blocked_trade.get("execution_error", ""), blocked_trade

    under_cap = _option_trade(premium=4.00, contracts=2)  # 800 <= cap
    status, submitted_trade = asyncio.run(
        orchestrator.submit_approved_screening_trade(
            under_cap,
            candidates=[],
            current_params={"stop_loss_pct": -0.02, "take_profit_pct": 0.05},
        )
    )
    assert len(fake.submitted) == 1, fake.submitted
    assert getattr(fake.submitted[0], "symbol") == "SPY261218C00500000"
    assert status == "failure", (status, submitted_trade)
    assert submitted_trade.get("execution_error") is None, submitted_trade

    print("[OK] smoke_option_notional_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
