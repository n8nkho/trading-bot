"""Adaptive RSI — screener + entry alignment tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestAdaptiveRsi(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data = Path(self._td.name)

    def test_ceiling_follows_entry_si_overrides(self):
        from utils import adaptive_rsi as ar

        params = self.data / "current_params.json"
        params.write_text(json.dumps({"rsi_threshold": 43}), encoding="utf-8")
        entry_ov = self.data / "entry_si_overrides.json"
        entry_ov.write_text(
            json.dumps({"active": True, "relaxed_rsi_cap": 70}),
            encoding="utf-8",
        )
        with patch.object(ar, "_CURRENT_PARAMS", params):
            with patch("utils.classic_si_entry._OVERRIDES_PATH", entry_ov):
                with patch(
                    "utils.fill_recency_entry.loosen_context",
                    return_value={"active": True, "relaxed_rsi_cap": 70},
                ):
                    ctx = ar.adaptive_rsi_context()
        self.assertEqual(ctx["ceiling"], 70.0)
        self.assertIn("fill_recency_entry", ctx["sources"])

    def test_tier_rsi_threshold_raises_tier1_to_ceiling(self):
        from utils import adaptive_rsi as ar

        with patch.object(ar, "adaptive_rsi_ceiling", return_value=70.0):
            out = ar.tier_rsi_threshold(tier_rsi=48.0, tier_idx=1)
        self.assertEqual(out, 70.0)

    def test_ranging_oversold_uses_adaptive_when_fill_recency_active(self):
        from utils import adaptive_rsi as ar

        with patch.object(
            ar,
            "adaptive_rsi_context",
            return_value={"ceiling": 70.0, "fill_recency_active": True},
        ):
            self.assertEqual(ar.adaptive_ranging_oversold_cap(), 70.0)


class TestClassicSiScreenerReset(unittest.TestCase):
    def test_reset_clears_stale_bear_overrides(self):
        from utils import classic_si_screener as css

        with tempfile.TemporaryDirectory() as td:
            ov_path = Path(td) / "overrides.json"
            ov_path.write_text(
                json.dumps(
                    {
                        "relax_step": 0,
                        "bear_rsi_t1": 48,
                        "bear_drop_min": -8,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(css, "_OVERRIDES_PATH", ov_path):
                css.reset_relax_on_candidates(candidates_found=3)
                doc = json.loads(ov_path.read_text(encoding="utf-8"))
            self.assertEqual(doc.get("relax_step"), 0)
            self.assertNotIn("bear_rsi_t1", doc)


class TestClassicScreeningHooks(unittest.TestCase):
    def test_zero_candidates_triggers_screener_relax(self):
        from utils import classic_screening_hooks as csh

        with patch("utils.pipeline_health.record_screening_outcome", return_value={}):
            with patch("utils.classic_si_screener.reset_relax_on_candidates"):
                with patch("utils.classic_si_recursive.reset_relax_on_candidates"):
                    with patch(
                        "utils.classic_si_screener.maybe_auto_relax_screener",
                        return_value={"ok": True},
                    ) as relax:
                        with patch(
                            "utils.classic_si_recursive.maybe_auto_relax_recursive",
                            return_value={"skipped": "x"},
                        ):
                            with patch(
                                "utils.classic_si_entry.maybe_auto_relax_entry_gate",
                                return_value={"skipped": "y"},
                            ):
                                out = csh.post_screening_si_hooks(candidates_found=0)
        relax.assert_called_once()
        self.assertTrue(out.get("screener_si", {}).get("ok"))


if __name__ == "__main__":
    unittest.main()
