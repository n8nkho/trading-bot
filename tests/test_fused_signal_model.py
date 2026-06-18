import json
import os
import unittest
from pathlib import Path
from unittest import mock

from utils.fused_signal_model import compute_symbol_score, load_weights


class TestFusedSignalModel(unittest.TestCase):
    def test_load_weights_equal_default(self):
        w = load_weights()
        self.assertIn("regime", w)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=3)

    def test_compute_symbol_score_bounded(self):
        with mock.patch("utils.fused_signal_model._read_json", return_value={}):
            row = compute_symbol_score("AAPL")
        self.assertEqual(row["symbol"], "AAPL")
        self.assertGreaterEqual(row["fused_score"], -1.0)
        self.assertLessEqual(row["fused_score"], 1.0)
        self.assertIn("components", row)

    def test_advisory_log_only_by_default(self):
        from utils.fused_signal_model import apply_fused_signal_advisory

        decision = {"ticker": "AAPL", "action": "BUY", "confidence": 0.6}
        with mock.patch.dict(os.environ, {"FORTRESS_FUSED_SIGNAL_ENABLED": "1"}, clear=False):
            out = apply_fused_signal_advisory(decision, fused_row={"fused_score": 0.5, "components": {}})
        self.assertEqual(out["confidence"], 0.6)
        self.assertEqual(out["fused_signal_advisory"]["mode"], "log_only")

    def test_confidence_nudge_when_affects_entry(self):
        from utils.fused_signal_model import apply_fused_signal_advisory

        decision = {"ticker": "AAPL", "action": "BUY", "confidence": 0.6}
        env = {"FORTRESS_FUSED_SIGNAL_ENABLED": "1", "FORTRESS_FUSED_SIGNAL_AFFECTS_ENTRY": "1"}
        with mock.patch.dict(os.environ, env, clear=False):
            out = apply_fused_signal_advisory(decision, fused_row={"fused_score": 1.0, "components": {}})
        self.assertGreater(out["confidence"], 0.6)
        self.assertEqual(out["fused_signal_advisory"]["mode"], "confidence_nudge")


if __name__ == "__main__":
    unittest.main()
