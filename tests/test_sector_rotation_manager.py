from __future__ import annotations

import unittest

from agents.sector_rotation_manager import build_monthly_rotation_signal


class TestSectorRotationManager(unittest.TestCase):
    def test_build_signal_top_three_and_weights(self):
        signal = build_monthly_rotation_signal(
            sector_history={
                "monthly_relative_strength": {
                    "XLK": 1.5,
                    "XLV": 1.2,
                    "XLF": 1.1,
                    "XLE": 0.3,
                }
            },
            vix=27.0,
            portfolio_value=20_000,
            allocation_pct=30.0,
        )
        picks = signal["signals"]
        self.assertEqual(len(picks), 3)
        self.assertEqual(picks[0]["sector"], "XLK")
        self.assertEqual([p["weight_pct"] for p in picks], [50.0, 30.0, 20.0])
        self.assertEqual(signal["macro_quadrant"], "inflation_shock")


if __name__ == "__main__":
    unittest.main()

