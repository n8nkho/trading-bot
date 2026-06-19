"""Pipeline health tracking for classic SI."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import pipeline_health as ph


class TestPipelineHealth(unittest.TestCase):
    def test_record_daily_screen_outcome_increments_zero_streak(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "health.json"
            with patch.object(ph, "_PATH", path):
                ph.record_daily_screen_outcome(candidates_found=0, raw_candidates_found=7)
                out = ph.record_daily_screen_outcome(candidates_found=0, raw_candidates_found=6)
            self.assertEqual(out["daily_screen_consecutive_zero"], 2)
            self.assertEqual(out["daily_screen_last_raw_candidates"], 6)
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("daily_screen_attrition_warn", doc)
            self.assertEqual(doc["daily_screen_last_candidates"], 0)

    def test_record_daily_screen_outcome_resets_on_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "health.json"
            path.write_text(json.dumps({"daily_screen_consecutive_zero": 2}), encoding="utf-8")
            with patch.object(ph, "_PATH", path):
                out = ph.record_daily_screen_outcome(candidates_found=1)
            self.assertEqual(out["daily_screen_consecutive_zero"], 0)


if __name__ == "__main__":
    unittest.main()
