#!/usr/bin/env python3
"""Smoke: HITL pending queue preserves failed submissions and corrupt queues."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import types
from pathlib import Path


def _stub_module(name: str, **attrs) -> None:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod


def _install_orchestrator_import_stubs() -> None:
    alpaca = types.ModuleType("alpaca")
    trading = types.ModuleType("alpaca.trading")
    client = types.ModuleType("alpaca.trading.client")
    requests = types.ModuleType("alpaca.trading.requests")
    enums = types.ModuleType("alpaca.trading.enums")

    class _TradingClient:
        def __init__(self, *args, **kwargs):
            pass

    class _Request:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

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
    _stub_module("agents.intraday_sniper", scan_intraday_opportunities=lambda *a, **k: [], evaluate_quick_entry=lambda *a, **k: {})
    _stub_module("utils.grok_sentiment", check_twitter_sentiment=lambda *a, **k: None)
    _stub_module("utils.option_contract_schema", normalize_option_decision=lambda x: x)
    _stub_module("utils.policy_profile", get_profile_bundle=lambda *a, **k: {"active_profile": "balanced", "risk": {}, "execution": {}})
    _stub_module("utils.trust_ledger", append_trust_event=lambda *a, **k: None)
    _stub_module(
        "utils.run_registry",
        log_screening_completed=lambda *a, **k: None,
        log_screening_failed=lambda *a, **k: None,
        log_screening_started=lambda *a, **k: None,
    )
    _stub_module(
        "utils.pre_trade_gate",
        evaluate_pre_trade_submission=lambda *a, **k: {"allowed": True, "reasons": []},
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
    _stub_module("utils.execution_mode", get_execution_mode=lambda *a, **k: "autonomous")


def main() -> int:
    from utils.pending_execution_queue import append_pending_batch, load_batches

    td = Path(tempfile.mkdtemp())
    try:
        data_dir = td / "data"
        data_dir.mkdir()

        queue_path = append_pending_batch(
            source="smoke",
            run_id="initial",
            candidates=[],
            trades=[{"ticker": "KEEP", "shares": 1, "entry_price": 10.0}],
            data_dir=data_dir,
        )
        queue_path.write_text("{broken json", encoding="utf-8")
        try:
            append_pending_batch(
                source="smoke",
                run_id="new",
                candidates=[],
                trades=[{"ticker": "NEW", "shares": 1, "entry_price": 10.0}],
                data_dir=data_dir,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("append_pending_batch should fail closed on corrupt JSON")
        assert queue_path.read_text(encoding="utf-8") == "{broken json"

        _install_orchestrator_import_stubs()
        os.environ["ALPACA_BASE_URL"] = "https://paper-api.alpaca.markets"
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_SECRET_KEY", None)
        import orchestrator

        orchestrator.DATA_DIR = data_dir
        append_pending_batch(
            source="smoke",
            run_id="flush",
            candidates=[],
            trades=[
                {"ticker": "OK", "shares": 1, "entry_price": 10.0},
                {"ticker": "FAIL", "shares": 1, "entry_price": 20.0},
            ],
            data_dir=data_dir,
        )

        async def _fake_submit(trade, candidates, current_params):
            if trade["ticker"] == "OK":
                return ("success", dict(trade))
            failed = dict(trade)
            failed["execution_error"] = "broker_down"
            return ("failure", failed)

        orchestrator.submit_approved_screening_trade = _fake_submit
        orchestrator.load_current_params = lambda: {"stop_loss_pct": -0.02, "take_profit_pct": 0.05}
        orchestrator.append_trust_event = lambda *a, **k: None

        out = orchestrator.flush_pending_execution_queue()
        assert out["executed"] == 1, out
        assert out["failed"] == 1, out
        batches = load_batches(data_dir)
        retained = [t for b in batches for t in b.get("trades", [])]
        assert [t["ticker"] for t in retained] == ["FAIL"], retained
        assert retained[0]["execution_error"] == "broker_down"
    finally:
        shutil.rmtree(td, ignore_errors=True)

    print("[OK] smoke_pending_execution_queue_safety")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
