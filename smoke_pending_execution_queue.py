#!/usr/bin/env python3
"""Smoke: execute_pending retains failed trades for retry."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path


def main() -> int:
    os.environ.setdefault("APCA_API_KEY_ID", "smoke_dummy_key")
    os.environ.setdefault("APCA_API_SECRET_KEY", "smoke_dummy_secret")
    import orchestrator as orch

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        orch.DATA_DIR = data_dir
        orch.POSITIONS_FILE = data_dir / "positions.json"
        orch.PNL_LEDGER_FILE = data_dir / "pnl_ledger.jsonl"
        orch.load_current_params = lambda: {"stop_loss_pct": -2.0, "take_profit_pct": 5.0}
        orch.append_trust_event = lambda *args, **kwargs: None

        queue_path = data_dir / "pending_execution_queue.json"
        queue_path.write_text(
            json.dumps(
                {
                    "batches": [
                        {
                            "updated_at": "2026-01-01T00:00:00",
                            "source": "smoke",
                            "run_id": "smoke_run",
                            "candidates": [{"ticker": "AAPL", "sector": "Technology"}],
                            "trades": [
                                {"ticker": "AAPL", "shares": 1, "entry_price": 100.0},
                                {"ticker": "MSFT", "shares": 1, "entry_price": 200.0},
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        async def fake_submit(trade, candidates, current_params):
            await asyncio.sleep(0)
            if trade["ticker"] == "AAPL":
                trade = dict(trade)
                trade["executed"] = True
                return ("success", trade)
            trade = dict(trade)
            trade["executed"] = False
            trade["execution_error"] = "smoke broker failure"
            return ("failure", trade)

        orch.submit_approved_screening_trade = fake_submit

        out = orch.flush_pending_execution_queue()
        assert out["executed"] == 1 and out["failed"] == 1, out

        retained = json.loads(queue_path.read_text(encoding="utf-8"))
        batches = retained.get("batches")
        assert len(batches) == 1, retained
        assert batches[0]["run_id"] == "smoke_run", batches[0]
        assert len(batches[0]["trades"]) == 1, batches[0]
        assert batches[0]["trades"][0]["ticker"] == "MSFT", batches[0]
        assert batches[0]["trades"][0]["execution_error"] == "smoke broker failure", batches[0]

    print("[OK] smoke_pending_execution_queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
