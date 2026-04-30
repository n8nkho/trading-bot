from __future__ import annotations

import unittest

from utils.execution_advisor import advise_execution


class TestExecutionAdvisor(unittest.TestCase):
    def test_high_confidence_high_volume_prefers_marketable_limit(self):
        out = advise_execution(confidence=0.9, volume_ratio=2.0, regime_label="RISK_ON")
        self.assertEqual(out["tactic"], "marketable_limit")
        self.assertEqual(out["urgency"], "high")


if __name__ == "__main__":
    unittest.main()
