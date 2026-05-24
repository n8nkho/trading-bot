"""
Smoke test: intraday sniper must honor strict hedge gates and human-in-the-loop mode.
"""

import os
import tempfile
from pathlib import Path


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
