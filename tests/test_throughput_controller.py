from __future__ import annotations

import unittest

from utils.throughput_controller import recommend_thresholds


class TestThroughputController(unittest.TestCase):
    def test_recommend_increase_when_below_band(self):
        out = recommend_thresholds(
            current_params={"rsi_threshold": 40, "volume_ratio_min": 1.5, "drop_min": -15, "drop_max": -5},
            candidates_found=0,
            target_min=2,
            target_max=5,
        )
        self.assertTrue(out["changed"])
        rp = out["recommended_params"]
        self.assertGreaterEqual(float(rp["rsi_threshold"]), 41.0)

    def test_recommend_no_change_within_band(self):
        out = recommend_thresholds(
            current_params={"rsi_threshold": 40, "volume_ratio_min": 1.5, "drop_min": -15, "drop_max": -5},
            candidates_found=3,
            target_min=2,
            target_max=5,
        )
        self.assertFalse(out["changed"])


if __name__ == "__main__":
    unittest.main()
