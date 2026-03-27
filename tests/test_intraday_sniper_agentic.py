from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.intraday_sniper import load_sniper_agentic_symbols


class TestIntradaySniperAgentic(unittest.TestCase):
    def test_load_sniper_agentic_symbols_filters_theme_and_consensus(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "scout_opportunity_queue_20260326.json").write_text(
                json.dumps(
                    {
                        "opportunities": [
                            {"symbol": "QQQ", "theme": "event_breakout"},
                            {"symbol": "IWM", "theme": "volatility_dislocation"},
                            {"symbol": "AAPL", "theme": "post_earnings_drift"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "analyst_consensus_20260326.json").write_text(
                json.dumps(
                    {
                        "recommendations": [
                            {"symbol": "QQQ", "consensus_score": 0.62, "recommendation": "BUY"},
                            {"symbol": "IWM", "consensus_score": 0.59, "recommendation": "BUY"},
                            {"symbol": "AAPL", "consensus_score": 0.75, "recommendation": "BUY"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = load_sniper_agentic_symbols(root, min_consensus=0.60)
            self.assertEqual(out, ["QQQ"])


if __name__ == "__main__":
    unittest.main()

