from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.pre_trade_gate import evaluate_pre_trade_submission
from utils.trading_guardrails import compute_loss_metrics, validate_llm_trade_output


class TestGuardrailExtensions(unittest.TestCase):
    def test_llm_trade_output_validation(self):
        ok, reason = validate_llm_trade_output("AAPL", "Momentum improving, support held.")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

        bad_ok, bad_reason = validate_llm_trade_output("AAPLLL", "Looks great.")
        self.assertFalse(bad_ok)
        self.assertEqual(bad_reason, "hallucinated_ticker_format")

    def test_compute_loss_metrics(self):
        out = compute_loss_metrics(
            {
                "current_equity": 9000.0,
                "peak_30d_equity": 10000.0,
                "daily_start_equity": 9500.0,
                "equity_1h_ago": 9300.0,
            }
        )
        self.assertAlmostEqual(out["drawdown_from_peak"], 0.10, places=6)
        self.assertAlmostEqual(out["daily_loss_pct"], (9500.0 - 9000.0) / 9500.0, places=6)
        self.assertAlmostEqual(out["hourly_equity_velocity"], abs((9000.0 - 9300.0) / 9000.0), places=6)

    def test_pre_trade_blackout_window_blocks_buy(self):
        now_et = datetime.now(ZoneInfo("America/New_York"))
        start = f"{now_et.hour:02d}:{max(0, now_et.minute-1):02d}"
        end = f"{now_et.hour:02d}:{min(59, now_et.minute+1):02d}"
        os.environ["FORTRESS_ENTRY_BLACKOUT_WINDOWS_ET"] = f"{start}-{end}"
        try:
            gate = evaluate_pre_trade_submission(side="BUY", symbol="AAPL", qty=1, estimated_notional_usd=100)
            self.assertFalse(gate["allowed"])
            self.assertTrue(any(r.startswith("event_blackout_window:") for r in gate["reasons"]))
        finally:
            os.environ.pop("FORTRESS_ENTRY_BLACKOUT_WINDOWS_ET", None)


if __name__ == "__main__":
    unittest.main()
