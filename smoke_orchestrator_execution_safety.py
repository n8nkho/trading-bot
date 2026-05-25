#!/usr/bin/env python3
"""Smoke tests for high-impact orchestrator execution safety gates."""

from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _import_orchestrator():
    os.environ.setdefault("APCA_API_KEY_ID", "smoke_dummy_key")
    os.environ.setdefault("APCA_API_SECRET_KEY", "smoke_dummy_secret")
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
