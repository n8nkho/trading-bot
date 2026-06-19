"""Adaptive RSI reconciliation tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestAdaptiveRsiReconciliation(unittest.TestCase):
    def test_detects_tight_screener_when_entry_relaxed(self):
        from utils import adaptive_rsi_reconciliation as arr

        with tempfile.TemporaryDirectory() as td:
            meta = Path(td) / "meta.json"
            meta.write_text(
                json.dumps(
                    {
                        "market_regime_at_screen": "VOLATILE",
                        "adaptive_rsi": {"ceiling": 70.0},
                        "prefilter_reject_samples": [
                            {"reason": "rsi_criteria", "rsi_rule": "lt_48", "ticker": "SPY"},
                            {"reason": "rsi_criteria", "rsi_rule": "lt_48", "ticker": "IWM"},
                            {"reason": "rsi_criteria", "rsi_rule": "lt_53", "ticker": "JPM"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            ov = Path(td) / "entry.json"
            ov.write_text(json.dumps({"active": True, "relaxed_rsi_cap": 70}), encoding="utf-8")
            with patch.object(arr, "_META", meta), patch.object(arr, "_ENTRY_OV", ov):
                findings = arr.scan_adaptive_rsi_screener_drift()
        self.assertEqual(findings[0]["code"], "adaptive_rsi_screener_drift")


if __name__ == "__main__":
    unittest.main()
