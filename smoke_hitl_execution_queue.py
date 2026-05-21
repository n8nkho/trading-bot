#!/usr/bin/env python3
"""Smoke: HITL execute_pending keeps failed submissions queued for retry."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    # Prevent import-time credential validation failures.
    os.environ.setdefault("APCA_API_KEY_ID", "DUMMY")
    os.environ.setdefault("APCA_API_SECRET_KEY", "DUMMY")
    os.environ.setdefault("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

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

    print("[OK] smoke_hitl_execution_queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
