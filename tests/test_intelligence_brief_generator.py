from __future__ import annotations

import json
import os
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytz

from agents.intelligence_brief_generator import generate_brief, generate_markdown_summary


class TestIntelligenceBriefGenerator(unittest.TestCase):
    def test_generate_brief_minimal(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            logs = root / "logs"
            data.mkdir(parents=True, exist_ok=True)
            logs.mkdir(parents=True, exist_ok=True)

            (data / "analyst_consensus_20260326.json").write_text(
                json.dumps(
                    {
                        "recommendations": [
                            {"symbol": "IWM", "consensus_score": 0.64, "recommendation": "BUY"},
                            {"symbol": "QQQ", "consensus_score": 0.55, "recommendation": "WATCH"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (data / "scout_opportunity_queue_20260326.json").write_text(
                json.dumps({"opportunities": [{"symbol": "IWM", "source": "volatility_scout"}]}),
                encoding="utf-8",
            )
            (data / "cio_directive_20260326.json").write_text(
                json.dumps({"portfolio_directive": "BALANCED", "vix": 25.3}),
                encoding="utf-8",
            )
            (data / "risk_guardian_state.json").write_text(
                json.dumps({"consecutive_losses": 1, "circuit_breaker_active": False}),
                encoding="utf-8",
            )

            now = datetime(2026, 3, 26, 17, 0, tzinfo=pytz.timezone("America/New_York"))
            cwd = os.getcwd()
            try:
                os.chdir(root)
                brief = generate_brief(data_dir=data, logs_dir=logs, now_et=now)
            finally:
                os.chdir(cwd)

            self.assertIn("meta", brief)
            self.assertIn("executive_summary", brief)
            self.assertIn("qa_checklist", brief)
            self.assertIn("agentic_intelligence", brief)
            self.assertEqual((brief["agentic_intelligence"]["analyst_consensus"] or {}).get("buy_recommendations"), 1)

            md = generate_markdown_summary(brief)
            self.assertIn("Executive Summary", md)
            self.assertIn("QA Checklist", md)


if __name__ == "__main__":
    unittest.main()

