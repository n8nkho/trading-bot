import os
import unittest
from unittest import mock

from utils.trusttrade_entry import (
    attach_screener_context,
    critique_consensus_needed,
    layer2_score_from_candidate,
)


class TestTrustTradeEntry(unittest.TestCase):
    def test_layer2_from_candidate(self):
        c = {"recursive_screener": {"layer2_score": 72.5}}
        self.assertEqual(layer2_score_from_candidate(c), 72.5)

    def test_attach_screener_context(self):
        decision = {"ticker": "AAPL", "action": "BUY"}
        candidate = {"recursive_screener": {"layer2_score": 80.0, "layer2_card": {}}}
        out = attach_screener_context(decision, candidate)
        self.assertEqual(out["layer2_score"], 80.0)
        self.assertIn("recursive_screener", out)

    def test_high_l2_skips_critique(self):
        with mock.patch.dict(os.environ, {"FORTRESS_TRUSTTRADE_ENTRY": "1"}, clear=False):
            need, reason = critique_consensus_needed(
                {"action": "BUY", "layer2_score": 78.0, "fused_signal_advisory": {"fused_score": 0.4}}
            )
        self.assertFalse(need)
        self.assertEqual(reason, "high_l2_skip_critique")

    def test_borderline_l2_requires_consensus(self):
        with mock.patch.dict(os.environ, {"FORTRESS_TRUSTTRADE_ENTRY": "1"}, clear=False):
            need, reason = critique_consensus_needed(
                {"action": "BUY", "layer2_score": 65.0, "fused_signal_advisory": {"fused_score": 0.2}}
            )
        self.assertTrue(need)
        self.assertEqual(reason, "borderline_l2_consensus")

    def test_borderline_fused_on_high_l2_still_needs_consensus(self):
        with mock.patch.dict(os.environ, {"FORTRESS_TRUSTTRADE_ENTRY": "1"}, clear=False):
            need, reason = critique_consensus_needed(
                {"action": "BUY", "layer2_score": 80.0, "fused_signal_advisory": {"fused_score": 0.05}}
            )
        self.assertTrue(need)
        self.assertEqual(reason, "borderline_fused_consensus")

    def test_trusttrade_disabled_always_needs_critique(self):
        with mock.patch.dict(os.environ, {"FORTRESS_TRUSTTRADE_ENTRY": "0"}, clear=False):
            need, reason = critique_consensus_needed({"action": "BUY", "layer2_score": 90.0})
        self.assertTrue(need)
        self.assertEqual(reason, "trusttrade_disabled")

    def test_l2_veto_bypass(self):
        from utils.trusttrade_entry import should_bypass_fused_veto

        with mock.patch.dict(os.environ, {"FORTRESS_TRUSTTRADE_ENTRY": "1"}, clear=False):
            ok, reason = should_bypass_fused_veto({"action": "BUY", "layer2_score": 81.0})
        self.assertTrue(ok)
        self.assertEqual(reason, "high_l2_fused_veto_bypass")
        with mock.patch.dict(os.environ, {"FORTRESS_TRUSTTRADE_ENTRY": "1"}, clear=False):
            ok, _ = should_bypass_fused_veto({"action": "BUY", "layer2_score": 70.0})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
