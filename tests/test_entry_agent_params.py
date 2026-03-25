"""Entry gate uses current_params rsi_threshold and optional window extension."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from agents import entry_agent


class TestEntryAgentParams(unittest.TestCase):
    def test_evaluate_single_entry_respects_rsi_threshold_kwarg(self):
        cand = {
            "ticker": "TEST",
            "rsi": 34.0,
            "current_price": 100.0,
            "analysis": {"confidence": 0.9},
        }
        with mock.patch.object(entry_agent, "yf") as yf_mock:
            import pandas as pd

            idx = pd.date_range("2026-03-25 14:00", periods=5, freq="min", tz="US/Eastern")
            yf_mock.Ticker.return_value.history.return_value = pd.DataFrame(
                {"Close": [100.0, 100.0, 100.0, 100.0, 100.0], "Low": [98.0, 98.0, 98.0, 98.0, 98.0], "High": [101.0] * 5},
                index=idx,
            )
            with mock.patch.object(entry_agent, "get_current_time_et") as tmock:
                from datetime import datetime

                tmock.return_value = datetime(2026, 3, 25, 15, 0, tzinfo=entry_agent.pytz.timezone("US/Eastern"))
                d_loose = entry_agent.evaluate_single_entry(cand, 50000, rsi_threshold=40.0)
                self.assertEqual(d_loose.get("action"), "BUY")
                d_tight = entry_agent.evaluate_single_entry(cand, 50000, rsi_threshold=30.0)
                self.assertEqual(d_tight.get("action"), "SKIP")

    def test_entry_window_extend_end_minutes(self):
        self.addCleanup(lambda: os.environ.pop("ENTRY_WINDOW_EXTEND_END_MINUTES", None))
        os.environ["ENTRY_WINDOW_EXTEND_END_MINUTES"] = "30"
        h, m = entry_agent._entry_window_end_with_extension()
        self.assertEqual((h, m), (16, 15))

    def test_evaluate_entry_uses_load_current_params_rsi(self):
        cand = {
            "ticker": "ZZZ",
            "rsi": 40.0,
            "current_price": 50.0,
            "analysis": {"confidence": 0.95},
        }
        with mock.patch("agents.performance_analyzer.load_current_params", return_value={"rsi_threshold": 50}):
            with mock.patch.object(entry_agent, "yf") as yf_mock:
                import pandas as pd

                idx = pd.date_range("2026-03-25 14:00", periods=5, freq="min", tz="US/Eastern")
                yf_mock.Ticker.return_value.history.return_value = pd.DataFrame(
                    {"Close": [50.0] * 5, "Low": [49.0] * 5, "High": [51.0] * 5},
                    index=idx,
                )
                with mock.patch.object(entry_agent, "get_current_time_et") as tmock:
                    from datetime import datetime

                    tmock.return_value = datetime(2026, 3, 25, 15, 0, tzinfo=entry_agent.pytz.timezone("US/Eastern"))
                    with mock.patch.object(entry_agent, "evaluate_option_trade", return_value=None):
                        decisions = entry_agent.evaluate_entry([cand], portfolio_value=50000)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].get("action"), "BUY")


if __name__ == "__main__":
    unittest.main()
