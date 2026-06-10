#!/usr/bin/env python3
"""Smoke: intraday sniper queues in HITL mode and refreshes autonomous fills."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _base_stubs(orch, data_dir: Path) -> dict:
    calls = {"submit": 0, "refresh": 0, "positions": []}
    orch.DATA_DIR = data_dir
    orch.POSITIONS_FILE = data_dir / "positions.json"
    orch.PNL_LEDGER_FILE = data_dir / "pnl_ledger.jsonl"
    orch.scan_intraday_opportunities = lambda portfolio_value: [
        {"ticker": "AAPL", "entry_price": 100.0, "metrics": {"volume_ratio": 2.0}}
    ]
    orch.evaluate_quick_entry = lambda ticker, entry_price, metrics, portfolio_value: {
        "action": "BUY",
        "shares": 2,
        "position_value": 200.0,
        "reason": "smoke",
        "confidence": 0.99,
    }
    orch.get_risk_status = lambda: {"consecutive_losses": 0, "circuit_breaker_active": False}
    orch.get_account_info = lambda: {
        "buying_power": 100000.0,
        "equity": 10000.0,
        "cash": 100000.0,
        "portfolio_value": 10000.0,
        "position_count": 0,
    }
    orch.load_positions = lambda: []
    orch.get_profile_bundle = lambda: {"execution": {"sniper_max_trades_per_run": 3}}
    orch.check_risk_limits = lambda portfolio_data, new_position, strict_mode=False: {"approved": True}
    orch.append_trust_event = lambda *args, **kwargs: None
    orch.add_position = lambda pos: calls["positions"].append(pos)
    return calls


def main() -> int:
    os.environ.setdefault("APCA_API_KEY_ID", "smoke_dummy_key")
    os.environ.setdefault("APCA_API_SECRET_KEY", "smoke_dummy_secret")
    import orchestrator as orch

    old_mode = os.environ.get("FORTRESS_EXECUTION_MODE")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            calls = _base_stubs(orch, data_dir)

            def fail_submit(*args, **kwargs):
                calls["submit"] += 1
                raise AssertionError("HITL sniper must not submit broker orders")

            orch.execute_buy_order = fail_submit
            os.environ["FORTRESS_EXECUTION_MODE"] = "human_in_loop"
            out = orch.run_intraday_sniper(10000.0)
            assert out["queued"] == 1 and out["executed"] == 0, out
            assert calls["submit"] == 0, calls
            assert calls["positions"] == [], calls

            queued = json.loads((data_dir / "pending_execution_queue.json").read_text())
            batch = queued["batches"][0]
            assert batch["source"] == "intraday_sniper", batch
            assert batch["trades"][0]["ticker"] == "AAPL", batch
            assert batch["trades"][0]["shares"] == 2, batch

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            calls = _base_stubs(orch, data_dir)

            def accepted_submit(ticker, shares, entry_price):
                calls["submit"] += 1
                return {
                    "success": True,
                    "order_id": "accepted_order",
                    "filled_qty": None,
                    "filled_price": None,
                    "status": "accepted",
                    "error": None,
                }

            def refresh_to_filled(order_result):
                calls["refresh"] += 1
                order_result = dict(order_result)
                order_result.update({"status": "filled", "filled_qty": 2, "filled_price": 100.0})
                return order_result

            orch.execute_buy_order = accepted_submit
            orch._refresh_order_result = refresh_to_filled
            os.environ["FORTRESS_EXECUTION_MODE"] = "autonomous"
            out = orch.run_intraday_sniper(10000.0)
            assert out["executed"] == 1 and out["queued"] == 0, out
            assert calls["submit"] == 1 and calls["refresh"] == 1, calls
            assert len(calls["positions"]) == 1, calls
            assert calls["positions"][0]["order_id"] == "accepted_order", calls
    finally:
        if old_mode is None:
            os.environ.pop("FORTRESS_EXECUTION_MODE", None)
        else:
            os.environ["FORTRESS_EXECUTION_MODE"] = old_mode

    print("[OK] smoke_snipe_hitl_queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
