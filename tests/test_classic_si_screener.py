"""Classic screener SI tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestClassicSiScreener(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data = Path(self._td.name)
        os.environ["FORTRESS_CLASSIC_SI_SCREENER"] = "1"

    def test_propose_relax_on_zero_streak(self):
        from unittest.mock import patch as mock_patch

        from utils import classic_si_screener as css

        with mock_patch.object(css, "_HEALTH_PATH", self.data / "health.json"):
            with mock_patch.object(css, "_META_PATH", self.data / "meta.json"):
                with mock_patch.object(css, "_RISK_PATH", self.data / "risk.json"):
                    with mock_patch.object(css, "_OVERRIDES_PATH", self.data / "overrides.json"):
                        (self.data / "health.json").write_text(
                            json.dumps({"consecutive_zero_runs": 3, "last_candidates_found": 0})
                        )
                        (self.data / "meta.json").write_text(
                            json.dumps({"market_regime_at_screen": "TRENDING_BEAR"})
                        )
                        (self.data / "risk.json").write_text(json.dumps({"regime": "TRENDING_BEAR"}))
                        proposed = css.propose_relax_patch()
        self.assertIsNotNone(proposed)
        self.assertEqual(proposed.get("relax_step"), 1)
        self.assertGreater(proposed.get("bear_rsi_t1", 0), 40)

    def test_apply_writes_overrides(self):
        from utils import classic_si_screener as css

        with patch.object(css, "_HEALTH_PATH", self.data / "health.json"):
            with patch.object(css, "_META_PATH", self.data / "meta.json"):
                with patch.object(css, "_RISK_PATH", self.data / "risk.json"):
                    with patch.object(css, "_OVERRIDES_PATH", self.data / "overrides.json"):
                        (self.data / "health.json").write_text(
                            json.dumps({"consecutive_zero_runs": 4, "last_candidates_found": 0})
                        )
                        (self.data / "risk.json").write_text(json.dumps({"regime": "RANGING"}))
                        result = css.apply_relax_patch({"relax_step": 1, "bear_rsi_t1": 48})
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("marker"), "classic_si_screener_relax")

    def test_effective_bear_tier1_reads_overrides(self):
        from utils import classic_si_screener as css

        with patch.object(css, "_OVERRIDES_PATH", self.data / "overrides.json"):
            with patch("utils.adaptive_rsi.adaptive_rsi_ceiling", return_value=40.0):
                (self.data / "overrides.json").write_text(
                    json.dumps({"relax_step": 1, "bear_rsi_t1": 50, "bear_drop_min": -5})
                )
                tier = css.effective_bear_tier1()
        self.assertEqual(tier["bear_rsi_t1"], 50)

    def test_daily_screen_zero_streak_drives_relax(self):
        from utils import classic_si_screener as css

        with patch.object(css, "_HEALTH_PATH", self.data / "health.json"):
            with patch.object(css, "_META_PATH", self.data / "meta.json"):
                with patch.object(css, "_RISK_PATH", self.data / "risk.json"):
                    with patch.object(css, "_OVERRIDES_PATH", self.data / "overrides.json"):
                        (self.data / "health.json").write_text(
                            json.dumps(
                                {
                                    "daily_screen_consecutive_zero": 2,
                                    "daily_screen_last_candidates": 0,
                                    "last_candidates_found": 7,
                                    "consecutive_zero_runs": 0,
                                }
                            )
                        )
                        (self.data / "risk.json").write_text(json.dumps({"regime": "VOLATILE"}))
                        proposed = css.propose_relax_patch()
        self.assertIsNotNone(proposed)


class TestClassicSiAutonomous(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        os.environ["FORTRESS_CLASSIC_SI_AUTO"] = "1"

    def test_scan_zero_finding(self):
        from utils import classic_si_autonomous as csa
        from utils import classic_si_screener as css

        with patch.object(css, "screening_context", return_value={"consecutive_zero_runs": 3, "last_candidates_found": 0, "regime": "TRENDING_BEAR", "filter_counts": {}}):
            with patch.object(css, "should_auto_relax", return_value=(True, "zero_candidate_streak")):
                f = csa.scan_zero_candidate_finding()
        self.assertIsNotNone(f)
        self.assertEqual(f.get("code"), "classic_zero_candidates")


if __name__ == "__main__":
    unittest.main()
