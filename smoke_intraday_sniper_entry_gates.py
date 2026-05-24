"""
Smoke test: intraday sniper must honor strict hedge gates and human-in-the-loop mode.
"""

import os
import sys
import tempfile
import types
from pathlib import Path


def _install_import_stubs():
    """Keep this focused smoke independent of heavyweight runtime dependencies."""
    dateutil_mod = types.ModuleType("dateutil")
    parser_mod = types.ModuleType("dateutil.parser")
    parser_mod.parse = lambda value: value
    dateutil_mod.parser = parser_mod
    sys.modules.setdefault("dateutil", dateutil_mod)
    sys.modules.setdefault("dateutil.parser", parser_mod)

    pytz_mod = types.ModuleType("pytz")
    pytz_mod.timezone = lambda name: None
    sys.modules.setdefault("pytz", pytz_mod)

    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *args, **kwargs: None
    sys.modules.setdefault("dotenv", dotenv_mod)

    alpaca_mod = types.ModuleType("alpaca")
    alpaca_trading_mod = types.ModuleType("alpaca.trading")
    alpaca_client_mod = types.ModuleType("alpaca.trading.client")
    alpaca_requests_mod = types.ModuleType("alpaca.trading.requests")
    alpaca_enums_mod = types.ModuleType("alpaca.trading.enums")

    class _TradingClient:
        def __init__(self, *args, **kwargs):
            pass

    class _Request:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _EnumValue:
        BUY = "buy"
        SELL = "sell"
        DAY = "day"
        CLOSED = "closed"

    alpaca_client_mod.TradingClient = _TradingClient
    alpaca_requests_mod.MarketOrderRequest = _Request
    alpaca_requests_mod.GetOrdersRequest = _Request
    alpaca_enums_mod.OrderSide = _EnumValue
    alpaca_enums_mod.TimeInForce = _EnumValue
    alpaca_enums_mod.QueryOrderStatus = _EnumValue
    sys.modules.setdefault("alpaca", alpaca_mod)
    sys.modules.setdefault("alpaca.trading", alpaca_trading_mod)
    sys.modules.setdefault("alpaca.trading.client", alpaca_client_mod)
    sys.modules.setdefault("alpaca.trading.requests", alpaca_requests_mod)
    sys.modules.setdefault("alpaca.trading.enums", alpaca_enums_mod)

    agents_mod = types.ModuleType("agents")
    agents_mod.__path__ = []
    sys.modules.setdefault("agents", agents_mod)
    _stub_module("agents.screener_agent", run_screener=lambda: [])
    _stub_module("agents.entry_agent", evaluate_entry=lambda candidates, portfolio_value: [])
    _stub_module("agents.exit_monitor", monitor_positions=lambda *args, **kwargs: None)
    _stub_module(
        "agents.risk_guardian",
        check_risk_limits=lambda *args, **kwargs: {"approved": True, "reason": "stub"},
        get_risk_limits=lambda *args, **kwargs: {},
        get_risk_status=lambda: {"consecutive_losses": 0, "circuit_breaker_active": False},
        update_consecutive_losses=lambda *args, **kwargs: None,
    )
    _stub_module(
        "agents.performance_analyzer",
        track_decision=lambda *args, **kwargs: None,
        load_current_params=lambda: {"stop_loss_pct": -2.0, "take_profit_pct": 15.0},
    )
    _stub_module(
        "agents.llama_watchdog",
        run_watchdog=lambda *args, **kwargs: None,
        preload_models=lambda *args, **kwargs: None,
        is_emergency_mode=lambda: False,
    )
    _stub_module("agents.document_analyst", quick_fundamental_check=lambda *args, **kwargs: None)
    _stub_module(
        "agents.intraday_sniper",
        scan_intraday_opportunities=lambda portfolio_value: [],
        evaluate_quick_entry=lambda *args, **kwargs: {},
    )

    _stub_module("utils.grok_sentiment", check_twitter_sentiment=lambda *args, **kwargs: None)
    _stub_module("utils.option_contract_schema", normalize_option_decision=lambda decision: decision)
    _stub_module("utils.policy_profile", get_profile_bundle=lambda: {})
    _stub_module("utils.trust_ledger", append_trust_event=lambda *args, **kwargs: None)
    _stub_module(
        "utils.run_registry",
        log_screening_completed=lambda *args, **kwargs: None,
        log_screening_failed=lambda *args, **kwargs: None,
        log_screening_started=lambda *args, **kwargs: None,
    )
    _stub_module(
        "utils.pre_trade_gate",
        evaluate_pre_trade_submission=lambda *args, **kwargs: {"allowed": True},
        format_gate_block_message=lambda gate: "blocked",
    )
    _stub_module(
        "utils.cost_calculator",
        get_daily_costs=lambda *args, **kwargs: {},
        get_monthly_projection=lambda *args, **kwargs: {},
        get_lifetime_costs=lambda *args, **kwargs: {},
        get_cost_per_trade=lambda *args, **kwargs: 0,
        generate_cost_report=lambda *args, **kwargs: {},
    )


def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules.setdefault(name, mod)


def _patch_common(orch, data_dir: Path, execution_mode: str, risk_status: dict, execute_calls: list, pending_batches: list):
    import utils.pending_execution_queue as peq

    orch.DATA_DIR = data_dir
    orch.append_trust_event = lambda *args, **kwargs: None
    orch.get_execution_mode = lambda: execution_mode
    orch.get_risk_status = lambda: risk_status
    orch.scan_intraday_opportunities = lambda portfolio_value: [
        {"ticker": "MOCK", "entry_price": 100.0, "metrics": {"volume_ratio": 2.0}}
    ]
    orch.evaluate_quick_entry = lambda ticker, entry_price, metrics, portfolio_value: {
        "ticker": ticker,
        "action": "BUY",
        "shares": 1,
        "position_value": 100.0,
        "entry_price": entry_price,
        "confidence": 0.9,
        "reason": "mock sniper setup",
    }
    orch.get_account_info = lambda: {
        "buying_power": 1e9,
        "equity": 10000.0,
        "cash": 1e9,
        "portfolio_value": 10000.0,
        "position_count": 0,
    }
    orch.load_positions = lambda: []
    orch.get_profile_bundle = lambda: {"execution": {"sniper_max_trades_per_run": 1}}
    orch.check_risk_limits = lambda portfolio_data, new_position, strict_mode=False: {
        "approved": True,
        "reason": "mock ok",
    }

    def _forbidden_execute(*args, **kwargs):
        execute_calls.append((args, kwargs))
        raise AssertionError("execute_buy_order should not be called")

    orch.execute_buy_order = _forbidden_execute

    def _capture_pending_batch(**kwargs):
        pending_batches.append(kwargs)
        return data_dir / "pending_execution_queue.json"

    peq.append_pending_batch = _capture_pending_batch


def main():
    # Avoid import-time Alpaca client initialization crashes (credentials required by alpaca-py).
    os.environ.setdefault("APCA_API_KEY_ID", "smoke_dummy_key")
    os.environ.setdefault("APCA_API_SECRET_KEY", "smoke_dummy_secret")
    _install_import_stubs()

    import orchestrator as orch

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)

        execute_calls = []
        pending_batches = []
        _patch_common(
            orch,
            data_dir,
            "autonomous",
            {"consecutive_losses": 2, "circuit_breaker_active": False},
            execute_calls,
            pending_batches,
        )
        strict_out = orch.run_intraday_sniper(portfolio_value=10000.0)
        assert strict_out["strict_mode"] is True
        assert strict_out["executed"] == 0
        assert strict_out["queued"] == 0
        assert strict_out["rejected"] == 1
        assert "HEDGE_GATE_FAILED" in strict_out["rejected_trades"][0]["reason"]
        assert execute_calls == []
        assert pending_batches == []

        execute_calls = []
        pending_batches = []
        _patch_common(
            orch,
            data_dir,
            "human_in_loop",
            {"consecutive_losses": 0, "circuit_breaker_active": False},
            execute_calls,
            pending_batches,
        )
        hitl_out = orch.run_intraday_sniper(portfolio_value=10000.0)
        assert hitl_out["strict_mode"] is False
        assert hitl_out["executed"] == 0
        assert hitl_out["queued"] == 1
        assert execute_calls == []
        assert len(pending_batches) == 1
        assert pending_batches[0]["source"] == "intraday_sniper"
        assert pending_batches[0]["trades"][0]["ticker"] == "MOCK"

    print("[smoke] smoke_intraday_sniper_entry_gates: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
