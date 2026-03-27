from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.screener_agent import load_agentic_opportunities


class TestScreenerAgentic(unittest.TestCase):
    def test_load_agentic_opportunities_filters_buy_and_consensus(self):
        with TemporaryDirectory() as td:
            data_dir = Path(td)
            (data_dir / "scout_opportunity_queue_20260326.json").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-26T15:00:00",
                        "opportunities": [
                            {"symbol": "IWM", "theme": "volatility_dislocation", "score": 0.66},
                            {"symbol": "QQQ", "theme": "event_breakout", "score": 0.58},
                            {"symbol": "MSFT", "theme": "mean_reversion", "score": 0.57},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "analyst_consensus_20260326.json").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-26T15:01:00",
                        "recommendations": [
                            {"symbol": "IWM", "consensus_score": 0.64, "recommendation": "BUY"},
                            {"symbol": "QQQ", "consensus_score": 0.59, "recommendation": "WATCH"},
                            {"symbol": "MSFT", "consensus_score": 0.61, "recommendation": "BUY"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "cio_directive_20260326.json").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-26T15:02:00",
                        "portfolio_directive": "BALANCED",
                        "sleeve_tilts_pct": {"day_trading": 30, "swing_trading": 40, "position_trading": 30},
                    }
                ),
                encoding="utf-8",
            )

            out = load_agentic_opportunities(data_dir=data_dir, min_consensus=0.60)
            syms = [x["ticker"] for x in out["symbols"]]
            self.assertEqual(syms, ["IWM", "MSFT"])
            self.assertEqual(out["cio_directive"], "BALANCED")
            self.assertAlmostEqual(float(out["agentic_budget_fraction"]), 0.70, places=3)

    def test_load_agentic_opportunities_graceful_when_missing(self):
        with TemporaryDirectory() as td:
            out = load_agentic_opportunities(data_dir=Path(td))
            self.assertEqual(out["agentic_count"], 0)
            self.assertEqual(out["symbols"], [])
            self.assertEqual(float(out["agentic_budget_fraction"]), 1.0)


if __name__ == "__main__":
    unittest.main()

