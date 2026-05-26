"""Drift rollback trigger gate — suppress false positives on ticket compression."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from utils import policy_guardrails as pg


class TestDriftRollbackTriggerGate(unittest.TestCase):
    def setUp(self):
        self.guard = {
            "auto_rollback_on_drift_alert": True,
            "rollback_trigger_suppress_win_rate": 0.80,
            "rollback_trigger_min_win_rate": 0.75,
        }
        self.drift = {
            "drift_alert": True,
            "recent_avg_pnl": 3.88,
            "prior_avg_pnl": 8.38,
            "drift_ratio": -0.54,
            "reason": "recent_performance_deterioration",
        }

    def test_suppresses_when_high_win_rate_and_positive_recent_avg(self):
        with patch.object(pg, "_pnl_ledger_stats", return_value={"count": 118, "win_rate": 0.873, "avg_pnl": 10.0}):
            with patch("utils.trading_activity.has_recent_trading_activity", return_value=True):
                ok, reason = pg.should_trigger_rollback_on_drift(self.drift, guard=self.guard)
        self.assertFalse(ok)
        self.assertIn("high_win_rate", reason)

    def test_triggers_when_win_rate_below_floor(self):
        with patch.object(pg, "_pnl_ledger_stats", return_value={"count": 118, "win_rate": 0.60, "avg_pnl": 1.0}):
            with patch("utils.trading_activity.has_recent_trading_activity", return_value=True):
                ok, reason = pg.should_trigger_rollback_on_drift(self.drift, guard=self.guard)
        self.assertTrue(ok)
        self.assertIn("win_rate_below_floor", reason)

    def test_maybe_trigger_skips_false_positive(self):
        with patch.object(pg, "_pnl_ledger_stats", return_value={"count": 118, "win_rate": 0.873, "avg_pnl": 10.0}):
            with patch("utils.trading_activity.has_recent_trading_activity", return_value=True):
                with patch.object(pg, "_load_rollback_state", return_value={}):
                    with patch.object(pg, "_save_rollback_state") as save:
                        out = pg.maybe_trigger_rollback_on_drift(self.drift)
        self.assertIsNone(out)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
