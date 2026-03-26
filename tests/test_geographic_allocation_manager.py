from __future__ import annotations

import unittest

from agents.geographic_allocation_manager import build_geographic_plan


class TestGeographicAllocationManager(unittest.TestCase):
    def test_build_geographic_plan_shape(self):
        plan = build_geographic_plan(portfolio_value=20_000, regime="RISK_OFF", vix=27.0)
        self.assertIn("international_capital_usd", plan)
        self.assertEqual(plan["international_capital_usd"], 4000.0)
        self.assertIsInstance(plan["allocations"], list)
        self.assertGreater(len(plan["allocations"]), 0)


if __name__ == "__main__":
    unittest.main()

