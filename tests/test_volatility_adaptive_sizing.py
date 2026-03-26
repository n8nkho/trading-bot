from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.volatility_adaptive_sizing import adaptive_position_size_pct, resolve_tier


class TestVolatilityAdaptiveSizing(unittest.TestCase):
    def test_tier_resolution(self):
        self.assertEqual(resolve_tier(12.0).name, "conservative")
        self.assertEqual(resolve_tier(20.0).name, "normal")
        self.assertEqual(resolve_tier(29.0).name, "aggressive")
        self.assertEqual(resolve_tier(40.0).name, "maximum_opportunity")

    def test_adaptive_cap_is_counter_cyclical(self):
        cap, tier = adaptive_position_size_pct(base_position_size_pct=3.0, vix=34.0)
        self.assertEqual(tier.name, "aggressive")
        self.assertEqual(cap, 4.0)

    def test_risk_guardian_includes_volatility_block(self):
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True, exist_ok=True)
            (data / "fortress_report_20260326.json").write_text(
                json.dumps({"market_conditions": {"vix": 36.0}}),
                encoding="utf-8",
            )
            cwd = os.getcwd()
            try:
                os.chdir(td)
                from agents.risk_guardian import get_risk_limits

                lim = get_risk_limits(strict_mode=False)
                va = lim.get("volatility_adaptive_sizing") or {}
                self.assertTrue(va.get("enabled"))
                self.assertEqual(va.get("tier"), "maximum_opportunity")
                self.assertGreaterEqual(float(lim.get("max_position_size_pct")), 5.0)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()

