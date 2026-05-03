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
                    with mock.patch.object(entry_agent, "evaluate_option_trade", return_value=None), mock.patch.object(
                        entry_agent, "_get_llm_engine"
                    ) as eng_mock:
                        eng_mock.return_value.evaluate_trade_opportunity.return_value = {"llm_available": False}
                        decisions = entry_agent.evaluate_entry([cand], portfolio_value=50000)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].get("action"), "BUY")

    def test_evaluate_entry_option_gating_outside_window_returns_list_of_dict(self):
        """
        Regression test:
        `evaluate_entry()` must always return a list[dict].
        A previous regression returned a dict early, which broke orchestrator screen.
        """
        cand = {
            "ticker": "TEST",
            "current_price": 100.0,
            "analysis": {"confidence": 0.9},
            "rsi": 10.0,
            "drop_pct": -10.0,
            "volume_ratio": 2.0,
            "news": [],
        }

        with mock.patch.object(entry_agent, "is_entry_window", return_value=False), mock.patch.object(
            entry_agent, "evaluate_option_trade", return_value={"strike": 100.0, "expiration": "2026-04-01", "premium": 2.0, "bid": 1.5, "ask": 1.6, "volume": 200.0, "contracts": 1, "cost": 200.0, "type": "OPTION"}
        ):
            out = entry_agent.evaluate_entry([cand], portfolio_value=20000.0)
        self.assertIsInstance(out, list)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], dict)
        self.assertEqual(out[0].get("action"), "SKIP")

    def test_execution_advisor_mode_off_does_not_attach_payload(self):
        cand = {
            "ticker": "TEST",
            "rsi": 20.0,
            "current_price": 100.0,
            "analysis": {"confidence": 0.9},
            "volume_ratio": 1.2,
        }
        with mock.patch.object(entry_agent, "yf") as yf_mock:
            import pandas as pd

            idx = pd.date_range("2026-03-25 14:00", periods=5, freq="min", tz="US/Eastern")
            yf_mock.Ticker.return_value.history.return_value = pd.DataFrame(
                {"Close": [100.0] * 5, "Low": [98.0] * 5, "High": [101.0] * 5},
                index=idx,
            )
            with mock.patch.object(entry_agent, "get_current_time_et") as tmock, mock.patch.object(
                entry_agent, "advise_execution"
            ) as advisor_mock:
                from datetime import datetime

                tmock.return_value = datetime(2026, 3, 25, 15, 0, tzinfo=entry_agent.pytz.timezone("US/Eastern"))
                with mock.patch.object(entry_agent, "_get_llm_engine") as eng_mock:
                    eng_mock.return_value.evaluate_trade_opportunity.return_value = {"llm_available": False}
                    d = entry_agent.evaluate_single_entry(
                        cand, 50000, rsi_threshold=40.0, execution_advisor_mode=0
                    )
        self.assertEqual(d.get("action"), "BUY")
        self.assertNotIn("execution_advisor", d)
        advisor_mock.assert_not_called()

    def test_execution_advisor_mode_shadow_attaches_payload_without_order_hint(self):
        cand = {
            "ticker": "TEST",
            "rsi": 20.0,
            "current_price": 100.0,
            "analysis": {"confidence": 0.9},
            "volume_ratio": 1.2,
        }
        with mock.patch.object(entry_agent, "yf") as yf_mock:
            import pandas as pd

            idx = pd.date_range("2026-03-25 14:00", periods=5, freq="min", tz="US/Eastern")
            yf_mock.Ticker.return_value.history.return_value = pd.DataFrame(
                {"Close": [100.0] * 5, "Low": [98.0] * 5, "High": [101.0] * 5},
                index=idx,
            )
            with mock.patch.object(entry_agent, "get_current_time_et") as tmock, mock.patch.object(
                entry_agent, "advise_execution", return_value={"tactic": "limit_mid"}
            ):
                from datetime import datetime

                tmock.return_value = datetime(2026, 3, 25, 15, 0, tzinfo=entry_agent.pytz.timezone("US/Eastern"))
                with mock.patch.object(entry_agent, "_get_llm_engine") as eng_mock:
                    eng_mock.return_value.evaluate_trade_opportunity.return_value = {"llm_available": False}
                    d = entry_agent.evaluate_single_entry(
                        cand, 50000, rsi_threshold=40.0, execution_advisor_mode=1
                    )
        self.assertEqual(d.get("action"), "BUY")
        self.assertIn("execution_advisor", d)
        self.assertNotIn("order_hint", d)


if __name__ == "__main__":
    unittest.main()
