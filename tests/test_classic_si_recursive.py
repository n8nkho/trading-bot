"""Classic RecursiveScreener SI tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestClassicSiRecursive(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data = Path(self._td.name)
        os.environ["FORTRESS_CLASSIC_SI_RECURSIVE"] = "1"

    def test_effective_min_layer2_score_default(self):
        from utils import classic_si_recursive as csr

        with patch.object(csr, "_OVERRIDES_PATH", self.data / "overrides.json"):
            self.assertEqual(csr.effective_min_layer2_score(), 65.0)

    def test_relax_on_high_attrition(self):
        from utils import classic_si_recursive as csr

        with patch.object(csr, "_HEALTH_PATH", self.data / "health.json"):
            with patch.object(csr, "_OVERRIDES_PATH", self.data / "overrides.json"):
                (self.data / "health.json").write_text(
                    json.dumps(
                        {
                            "daily_screen_last_raw_candidates": 7,
                            "daily_screen_last_candidates": 0,
                            "daily_screen_consecutive_zero": 1,
                        }
                    )
                )
                result = csr.apply_relax_patch()
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("effective_min_layer2_score"), 60.0)

    def test_reset_on_post_recursive_candidates(self):
        from utils import classic_si_recursive as csr

        with patch.object(csr, "_OVERRIDES_PATH", self.data / "overrides.json"):
            (self.data / "overrides.json").write_text(json.dumps({"relax_step": 2, "min_layer2_score": 55}))
            csr.reset_relax_on_candidates(candidates_found=2)
            ov = json.loads((self.data / "overrides.json").read_text())
        self.assertEqual(ov.get("relax_step"), 0)


if __name__ == "__main__":
    unittest.main()
