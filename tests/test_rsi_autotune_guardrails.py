from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class TestRsiAutotuneGuardrails(unittest.TestCase):
    def test_raises_rsi_by_one_when_rsi_skips_dominate(self):
        import orchestrator as orch

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            prev_data_dir = orch.DATA_DIR
            prev_load = orch.load_current_params
            prev_save = orch.save_current_params
            try:
                orch.DATA_DIR = tdp
                (tdp / "daily_signals_20260425.json").write_text(
                    json.dumps(
                        {
                            "entry_gate_summary": {
                                "buy_count": 0,
                                "skip_count": 5,
                                "top_skip_reasons": [
                                    {"reason": "RSI not oversold enough (43.5 >= 42.0)", "count": 3},
                                    {"reason": "Outside entry window (current: 12:00 ET, window: 14:30-16:00 ET)", "count": 1},
                                    {"reason": "RSI not oversold enough (44.1 >= 42.0)", "count": 1},
                                ],
                            }
                        }
                    ),
                    encoding="utf-8",
                )

                saved: dict = {}
                orch.load_current_params = lambda: {"rsi_threshold": 42, "stop_loss_pct": -2.0}

                def _save(params):
                    saved.update(params)

                orch.save_current_params = _save
                out = orch._auto_adjust_rsi_from_previous_run(
                    risk_status={"circuit_breaker_active": False, "consecutive_losses": 0}
                )
                self.assertTrue(out["changed"])
                self.assertEqual(out["new_rsi"], 43)
                self.assertEqual(saved.get("rsi_threshold"), 43)
            finally:
                orch.DATA_DIR = prev_data_dir
                orch.load_current_params = prev_load
                orch.save_current_params = prev_save

    def test_skips_adjustment_when_window_skips_dominate(self):
        import orchestrator as orch

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            prev_data_dir = orch.DATA_DIR
            prev_load = orch.load_current_params
            prev_save = orch.save_current_params
            try:
                orch.DATA_DIR = tdp
                (tdp / "daily_signals_20260425.json").write_text(
                    json.dumps(
                        {
                            "entry_gate_summary": {
                                "buy_count": 0,
                                "skip_count": 6,
                                "top_skip_reasons": [
                                    {"reason": "Outside entry window (current: 12:00 ET, window: 14:30-16:00 ET)", "count": 4},
                                    {"reason": "RSI not oversold enough (43.5 >= 42.0)", "count": 2},
                                ],
                            }
                        }
                    ),
                    encoding="utf-8",
                )

                called = {"save": 0}
                orch.load_current_params = lambda: {"rsi_threshold": 42, "stop_loss_pct": -2.0}
                orch.save_current_params = lambda _params: called.__setitem__("save", called["save"] + 1)

                out = orch._auto_adjust_rsi_from_previous_run(
                    risk_status={"circuit_breaker_active": False, "consecutive_losses": 0}
                )
                self.assertFalse(out["changed"])
                self.assertEqual(called["save"], 0)
            finally:
                orch.DATA_DIR = prev_data_dir
                orch.load_current_params = prev_load
                orch.save_current_params = prev_save


if __name__ == "__main__":
    unittest.main()

