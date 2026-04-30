from __future__ import annotations

import unittest

from agents.convergence_engine import score_candidate


class TestConvergenceEngine(unittest.TestCase):
    def test_score_candidate_returns_full_breakdown(self):
        cand = {
            "ticker": "AAPL",
            "drop_pct": -8.2,
            "rsi": 31.0,
            "volume_ratio": 1.9,
            "analysis": {"confidence": 0.74},
            "vision_signal": {"signal": "BUY"},
        }
        out = score_candidate(cand, regime_label="RISK_ON")
        self.assertIn("convergence_score", out)
        self.assertIn("factor_breakdown", out)
        self.assertGreaterEqual(float(out["convergence_score"]), 0.0)
        self.assertLessEqual(float(out["convergence_score"]), 100.0)
        self.assertEqual(out["regime_label"], "RISK_ON")
        self.assertIn("weights", out["factor_breakdown"])


if __name__ == "__main__":
    unittest.main()
