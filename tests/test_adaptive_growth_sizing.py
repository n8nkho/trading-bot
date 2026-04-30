from __future__ import annotations

import unittest

from utils.adaptive_growth_sizing import recommend_size


class TestAdaptiveGrowthSizing(unittest.TestCase):
    def test_recommendation_respects_caps(self):
        out = recommend_size(
            equity_usd=20000.0,
            current_price=100.0,
            confidence=0.9,
            deployed_usd=24000.0,
            overnight_exposure_usd=2000.0,
            overnight_candidate=True,
        )
        self.assertLessEqual(float(out["recommended_position_usd"]), 1000.0)
        self.assertLessEqual(int(out["recommended_shares"]), 10)


if __name__ == "__main__":
    unittest.main()
