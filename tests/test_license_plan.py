import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.license import get_plan


class LicensePlanTests(unittest.TestCase):
    def plan_with_env(self, env: dict[str, str]):
        with patch.dict(os.environ, env, clear=True):
            return get_plan()

    def test_no_license_file_mode_preserves_default_master(self):
        plan = self.plan_with_env({})

        self.assertEqual(plan.tier, "master")
        self.assertTrue(plan.valid)

    def test_configured_missing_license_file_fails_closed(self):
        plan = self.plan_with_env({"FORTRESS_LICENSE_PATH": "/tmp/does-not-exist-license.json"})

        self.assertEqual(plan.tier, "starter")
        self.assertFalse(plan.valid)

    def test_configured_invalid_json_license_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "license.json"
            path.write_text("{", encoding="utf-8")

            plan = self.plan_with_env({"FORTRESS_LICENSE_PATH": str(path)})

        self.assertEqual(plan.tier, "starter")
        self.assertFalse(plan.valid)

    def test_configured_empty_license_file_fails_closed_without_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "license.json"
            path.write_text("{}", encoding="utf-8")

            plan = self.plan_with_env({"FORTRESS_LICENSE_PATH": str(path)})

        self.assertEqual(plan.tier, "starter")
        self.assertFalse(plan.valid)

    def test_configured_license_file_tier_wins_over_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "license.json"
            path.write_text(json.dumps({"tier": "pro", "valid": True}), encoding="utf-8")

            plan = self.plan_with_env(
                {
                    "FORTRESS_LICENSE_PATH": str(path),
                    "FORTRESS_LICENSE_TIER": "master",
                }
            )

        self.assertEqual(plan.tier, "pro")
        self.assertTrue(plan.valid)

    def test_explicit_env_tier_can_break_glass_when_file_is_missing(self):
        plan = self.plan_with_env(
            {
                "FORTRESS_LICENSE_PATH": "/tmp/does-not-exist-license.json",
                "FORTRESS_LICENSE_TIER": "pro",
            }
        )

        self.assertEqual(plan.tier, "pro")
        self.assertTrue(plan.valid)


if __name__ == "__main__":
    unittest.main()
