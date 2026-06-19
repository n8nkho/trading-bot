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

    def test_fused_confidence_delta_capped_at_005(self):
        from utils.fused_signal_model import apply_fused_signal_advisory, max_confidence_delta

        env = {"FORTRESS_FUSED_SIGNAL_ENABLED": "1", "FORTRESS_FUSED_SIGNAL_AFFECTS_ENTRY": "1"}
        base_conf = 0.6
        cap = max_confidence_delta()
        self.assertAlmostEqual(cap, 0.05, places=4)
        cases = [(1.0, +cap), (-1.0, -cap), (10.0, +cap), (-10.0, -cap)]
        with mock.patch.dict(os.environ, env, clear=False):
            for score, expected_delta in cases:
                decision = {"ticker": "AAPL", "action": "BUY", "confidence": base_conf}
                out = apply_fused_signal_advisory(
                    decision,
                    fused_row={"fused_score": score, "components": {}},
                )
                self.assertAlmostEqual(
                    out["fused_signal_advisory"]["confidence_delta"],
                    expected_delta,
                    places=4,
                    msg=f"score={score}",
                )
                self.assertAlmostEqual(
                    out["confidence"],
                    base_conf + expected_delta,
                    places=4,
                    msg=f"score={score}",
                )

    def test_fused_veto_flips_buy_to_skip(self):
        from utils.fused_signal_model import apply_fused_entry_gates

        decision = {"ticker": "AAPL", "action": "BUY", "confidence": 0.6, "shares": 10, "position_size": 1000}
        env = {
            "FORTRESS_FUSED_SIGNAL_ENABLED": "1",
            "FORTRESS_FUSED_SIGNAL_VETO": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            out = apply_fused_entry_gates(
                decision,
                fused_row={"fused_score": -0.3, "components": {}},
            )
        self.assertEqual(out["action"], "SKIP")
        self.assertEqual(out["reject_stage"], "fused_signal_veto")
        self.assertEqual(out["shares"], 0)
        self.assertEqual(out["fused_signal_advisory"]["mode"], "veto")

    def test_fused_veto_allows_score_above_threshold(self):
        from utils.fused_signal_model import apply_fused_entry_gates

        decision = {"ticker": "AAPL", "action": "BUY", "confidence": 0.6}
        env = {
            "FORTRESS_FUSED_SIGNAL_ENABLED": "1",
            "FORTRESS_FUSED_SIGNAL_VETO": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            out = apply_fused_entry_gates(
                decision,
                fused_row={"fused_score": -0.2, "components": {}},
            )
        self.assertEqual(out["action"], "BUY")

    def test_fused_l2_bypass_overrides_veto(self):
        from utils.fused_signal_model import apply_fused_entry_gates

        decision = {
            "ticker": "V",
            "action": "BUY",
            "confidence": 0.75,
            "layer2_score": 81.6,
            "shares": 10,
            "position_size": 1000,
        }
        env = {
            "FORTRESS_FUSED_SIGNAL_ENABLED": "1",
            "FORTRESS_FUSED_SIGNAL_VETO": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            out = apply_fused_entry_gates(
                decision,
                fused_row={"fused_score": -0.3, "components": {}},
            )
        self.assertEqual(out["action"], "BUY")
        self.assertEqual(out["fused_signal_advisory"]["mode"], "l2_veto_bypass")
        self.assertEqual(out["fused_veto_bypass"]["reason"], "high_l2_fused_veto_bypass")


if __name__ == "__main__":
    unittest.main()
