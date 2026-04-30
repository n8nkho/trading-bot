from __future__ import annotations

import unittest

from utils.uplift_runtime import get_flag_mode, get_limits


class TestUpliftRuntime(unittest.TestCase):
    def test_flag_mode_is_bounded(self):
        mode = get_flag_mode("FORTRESS_UPLIFT_CONVERGENCE_MODE")
        self.assertIn(mode, (0, 1, 2))

    def test_limits_have_expected_keys(self):
        lim = get_limits()
        self.assertIn("max_total_deployed_usd", lim)
        self.assertIn("max_overnight_exposure_ratio", lim)
        self.assertIn("max_position_equity_ratio", lim)


if __name__ == "__main__":
    unittest.main()
