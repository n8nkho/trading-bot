from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory


class TestRiskGuardianAutoReset(unittest.TestCase):
    def _reload_risk_guardian(self):
        # Ensure the module re-imports and re-runs _load_risk_state()
        if "agents.risk_guardian" in sys.modules:
            del sys.modules["agents.risk_guardian"]
        return importlib.import_module("agents.risk_guardian")

    def test_auto_reset_when_state_is_stale(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir(parents=True, exist_ok=True)

            stale_time = datetime.now() - timedelta(hours=48)
            (root / "data" / "risk_guardian_state.json").write_text(
                json.dumps(
                    {
                        "consecutive_losses": 5,
                        "circuit_breaker_active": True,
                        "position_size_reduction": 0.5,
                        "updated_at": stale_time.isoformat(),
                    }
                ),
                encoding="utf-8",
            )

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                os.environ["FORTRESS_AUTO_RESET_RISK_GUARDIAN_STATE"] = "1"
                os.environ["FORTRESS_RISK_STATE_MAX_AGE_HOURS"] = "24"
                rg = self._reload_risk_guardian()
                st = rg.get_risk_status()
                self.assertEqual(st["consecutive_losses"], 0)
                self.assertFalse(st["circuit_breaker_active"])
            finally:
                os.chdir(old_cwd)
                os.environ.pop("FORTRESS_AUTO_RESET_RISK_GUARDIAN_STATE", None)
                os.environ.pop("FORTRESS_RISK_STATE_MAX_AGE_HOURS", None)

    def test_no_reset_when_state_is_fresh(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir(parents=True, exist_ok=True)

            fresh_time = datetime.now() - timedelta(hours=5)
            (root / "data" / "risk_guardian_state.json").write_text(
                json.dumps(
                    {
                        "consecutive_losses": 5,
                        "circuit_breaker_active": True,
                        "position_size_reduction": 0.5,
                        "updated_at": fresh_time.isoformat(),
                    }
                ),
                encoding="utf-8",
            )

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                os.environ["FORTRESS_AUTO_RESET_RISK_GUARDIAN_STATE"] = "1"
                os.environ["FORTRESS_RISK_STATE_MAX_AGE_HOURS"] = "24"
                rg = self._reload_risk_guardian()
                st = rg.get_risk_status()
                self.assertEqual(st["consecutive_losses"], 5)
                self.assertTrue(st["circuit_breaker_active"])
            finally:
                os.chdir(old_cwd)
                os.environ.pop("FORTRESS_AUTO_RESET_RISK_GUARDIAN_STATE", None)
                os.environ.pop("FORTRESS_RISK_STATE_MAX_AGE_HOURS", None)


if __name__ == "__main__":
    unittest.main()

