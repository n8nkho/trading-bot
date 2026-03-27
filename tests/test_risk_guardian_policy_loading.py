from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class TestRiskGuardianPolicyLoading(unittest.TestCase):
    def _reload_risk_guardian(self):
        if "agents.risk_guardian" in sys.modules:
            del sys.modules["agents.risk_guardian"]
        return importlib.import_module("agents.risk_guardian")

    def test_loads_opportunistic_profile(self):
        rg = self._reload_risk_guardian()
        status = rg.get_risk_status()
        self.assertEqual(status["policy_profile"], "opportunistic")
        self.assertEqual(status["max_positions"], 6)
        self.assertEqual(status["max_position_size_pct"], 3.5)
        self.assertEqual(status["max_total_risk_pct"], 8.0)

    def test_switches_profiles(self):
        rg = self._reload_risk_guardian()
        with patch.object(
            rg,
            "get_profile_bundle",
            return_value={
                "active_profile": "balanced",
                "risk": {
                    "max_positions": 5,
                    "max_position_size_pct": 3.0,
                    "max_total_risk_pct": 7.0,
                    "daily_loss_limit_pct": -2.0,
                    "weekly_loss_limit_pct": -5.0,
                },
            },
        ):
            status = rg.get_risk_status()
            self.assertEqual(status["policy_profile"], "balanced")
            self.assertEqual(status["max_positions"], 5)
            self.assertEqual(status["max_position_size_pct"], 3.0)
            self.assertEqual(status["max_total_risk_pct"], 7.0)

    def test_state_file_does_not_override_policy_limits(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir(parents=True, exist_ok=True)
            (root / "data" / "risk_guardian_state.json").write_text(
                json.dumps(
                    {
                        "consecutive_losses": 0,
                        "position_size_reduction": 1.0,
                        "circuit_breaker_active": False,
                        # Intentionally bogus; should be ignored as limits come from policy profile.
                        "max_positions": 99,
                        "max_position_size_pct": 99.0,
                        "max_total_risk_pct": 99.0,
                        "policy_profile": "opportunistic",
                    }
                ),
                encoding="utf-8",
            )

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                rg = self._reload_risk_guardian()
                status = rg.get_risk_status()
                self.assertEqual(status["max_positions"], 6)
                self.assertEqual(status["max_position_size_pct"], 3.5)
                self.assertEqual(status["max_total_risk_pct"], 8.0)
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()

