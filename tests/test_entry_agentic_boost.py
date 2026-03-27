from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agents import entry_agent


class TestEntryAgenticBoost(unittest.TestCase):
    def test_agentic_signal_boost_tagged_on_buy_recommendation(self):
        cand = {
            "ticker": "AAPL",
            "rsi": 10.0,
            "current_price": 100.0,
            "analysis": {"confidence": 0.50},
            "drop_pct": -10.0,
            "volume_ratio": 2.0,
            "news": [],
        }
        with TemporaryDirectory() as td:
            d = Path(td)
            (d / "data").mkdir(parents=True, exist_ok=True)
            (d / "data" / "analyst_consensus_20260326.json").write_text(
                json.dumps({"recommendations": [{"symbol": "AAPL", "consensus_score": 0.66, "recommendation": "BUY"}]}),
                encoding="utf-8",
            )
            cwd = os.getcwd()
            try:
                os.chdir(d)
                with mock.patch.object(entry_agent, "evaluate_option_trade", return_value=None), mock.patch.object(
                    entry_agent, "evaluate_single_entry", return_value={"ticker": "AAPL", "action": "BUY", "position_size": 100, "shares": 1}
                ):
                    out = entry_agent.evaluate_entry([cand], portfolio_value=20_000)
                self.assertEqual(out[0].get("signal_mode"), "agentic_signal_boost")
                self.assertGreaterEqual(float(cand["analysis"]["confidence"]), 0.60)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()

