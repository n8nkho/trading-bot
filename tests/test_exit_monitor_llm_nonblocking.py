"""
Regression: LLM HOLD/SKIP must not return before deterministic exit rails (stop, tiers, etc.).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd


class TestExitMonitorLLMNonBlocking(unittest.TestCase):
    def _mock_ticker(self, close: float) -> MagicMock:
        m = MagicMock()
        m.history.return_value = pd.DataFrame({"Close": [close]})
        return m

    def test_llm_hold_does_not_block_stop_loss(self):
        """High-confidence HOLD from LLM must still allow -2% stop."""
        pos = {
            "ticker": "TEST",
            "entry_price": 100.0,
            "qty": 10,
            "entry_date": "2025-01-01T12:00:00",
            "tiers_sold": {"tier1": False, "tier2": False, "tier3": False, "tier4": False},
        }
        eng = MagicMock()
        eng.evaluate_exit.return_value = {
            "llm_available": True,
            "decision": "HOLD",
            "confidence": 0.99,
            "reasoning": "stay invested",
        }
        with (
            patch("agents.exit_monitor.yf.Ticker", return_value=self._mock_ticker(97.0)),
            patch("agents.exit_monitor._get_llm_engine", return_value=eng),
            patch("agents.exit_monitor.get_trailing_state", return_value={}),
            patch(
                "agents.exit_monitor.check_negative_news",
                return_value={"has_negative_news": False, "summary": ""},
            ),
        ):
            from agents.exit_monitor import evaluate_exit

            d = evaluate_exit(pos)
        self.assertEqual(d["action"], "SELL_ALL")
        self.assertTrue(d.get("stop_loss"))

    def test_llm_exit_below_threshold_not_authoritative(self):
        """EXIT with confidence < 0.70 is advisory; tiers still apply."""
        pos = {
            "ticker": "TEST",
            "entry_price": 100.0,
            "qty": 100,
            "entry_date": (datetime.now() - timedelta(days=1)).isoformat(),
            "tiers_sold": {"tier1": False, "tier2": False, "tier3": False, "tier4": False},
        }
        eng = MagicMock()
        eng.evaluate_exit.return_value = {
            "llm_available": True,
            "decision": "EXIT",
            "confidence": 0.60,
            "reasoning": "take profit",
        }
        # +1.0% — above tier1 (+0.75%), below tier2 (+1.5%)
        with (
            patch("agents.exit_monitor.yf.Ticker", return_value=self._mock_ticker(101.0)),
            patch("agents.exit_monitor._get_llm_engine", return_value=eng),
            patch("agents.exit_monitor.get_trailing_state", return_value={}),
            patch(
                "agents.exit_monitor.check_negative_news",
                return_value={"has_negative_news": False, "summary": ""},
            ),
        ):
            from agents.exit_monitor import evaluate_exit

            d = evaluate_exit(pos)
        self.assertEqual(d["action"], "SELL_30%")
        self.assertEqual(d.get("tier"), "tier1")

    def test_llm_unavailable_skips_advisory_and_uses_tiers(self):
        eng = MagicMock()
        eng.evaluate_exit.return_value = {"llm_available": False, "decision": "HOLD", "confidence": 0.0}
        pos = {
            "ticker": "TEST",
            "entry_price": 100.0,
            "qty": 100,
            "entry_date": (datetime.now() - timedelta(days=1)).isoformat(),
            "tiers_sold": {"tier1": False, "tier2": False, "tier3": False, "tier4": False},
        }
        with (
            patch("agents.exit_monitor.yf.Ticker", return_value=self._mock_ticker(101.0)),
            patch("agents.exit_monitor._get_llm_engine", return_value=eng),
            patch("agents.exit_monitor.get_trailing_state", return_value={}),
            patch(
                "agents.exit_monitor.check_negative_news",
                return_value={"has_negative_news": False, "summary": ""},
            ),
        ):
            from agents.exit_monitor import evaluate_exit

            d = evaluate_exit(pos)
        self.assertEqual(d["action"], "SELL_30%")


if __name__ == "__main__":
    unittest.main()
