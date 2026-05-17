from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))


class TestWalkForwardValidator(unittest.TestCase):
    def test_compute_windows_and_stable_flag(self):
        from agents import walk_forward_validator as wf

        pnls = [1.0] * 7 + [-2.0] * 7
        with patch.object(wf, "LEDGER", Path("/tmp/does_not_exist_ledger")):
            with patch.object(wf, "_load_ledger_rows", return_value=[{"pnl": p} for p in pnls]):
                r = wf.compute_walk_forward_report()
        self.assertGreaterEqual(r["total_trades"], 14)
        self.assertEqual(r["reason"], "later_window_weaker")
        self.assertFalse(r["stable"])
        self.assertIn("windows", r)
        self.assertGreaterEqual(len(r["windows"]), 2)

    def test_insufficient_trades(self):
        from agents import walk_forward_validator as wf

        with patch.object(wf, "_load_ledger_rows", return_value=[{"pnl": 1.0}] * 5):
            r = wf.compute_walk_forward_report()
        self.assertEqual(r["reason"], "insufficient_trades")


if __name__ == "__main__":
    unittest.main()
