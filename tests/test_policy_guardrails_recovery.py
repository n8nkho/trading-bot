"""Metrics-driven early recovery from drift rollback."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from utils import policy_guardrails as pg


class TestPolicyGuardrailsRecovery(unittest.TestCase):
    def setUp(self):
        self.guard = {
            "rollback_recovery_on_metrics": True,
            "rollback_min_duration_hours": 12,
            "rollback_recovery_min_win_rate": 0.70,
            "rollback_recovery_min_recent_avg_pnl": 0.0,
        }
        self.active_state = {
            "forced_profile": "capital_preservation",
            "forced_reason": "drift_alert",
            "forced_at": (datetime.now() - timedelta(hours=24)).isoformat(),
            "forced_until": (datetime.now() + timedelta(days=5)).isoformat(),
            "drift_snapshot": {"drift_ratio": -0.58},
        }

    def test_recovery_on_positive_expectancy_despite_drift_alert(self):
        drift = {
            "drift_alert": True,
            "recent_avg_pnl": 3.74,
            "prior_avg_pnl": 8.85,
            "drift_ratio": -0.5774,
            "reason": "recent_performance_deterioration",
        }
        with patch.object(pg, "_pnl_ledger_stats", return_value={"count": 118, "win_rate": 0.864, "avg_pnl": 10.0}):
            ok, reason = pg.meets_rollback_recovery_criteria(drift, state=self.active_state, guard=self.guard)
        self.assertTrue(ok)
        self.assertTrue(str(reason).startswith("positive_expectancy"))

    def test_no_recovery_before_min_duration(self):
        state = dict(self.active_state)
        state["forced_at"] = datetime.now().isoformat()
        drift = {"drift_alert": False}
        ok, reason = pg.meets_rollback_recovery_criteria(drift, state=state, guard=self.guard)
        self.assertFalse(ok)
        self.assertIn("min_duration", reason)


if __name__ == "__main__":
    unittest.main()
