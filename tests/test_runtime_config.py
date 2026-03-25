"""Tests for utils.runtime_config."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class TestRuntimeConfig(unittest.TestCase):
    def test_defaults_when_missing_file(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "nope.yaml"
            os.environ["FORTRESS_RUNTIME_CONFIG"] = str(p)
            try:
                import utils.runtime_config as rc

                rc.get_runtime_config(reload=True)
                cfg = rc.get_runtime_config()
                self.assertTrue(cfg["agents"]["daily_screen"]["enabled"])
                self.assertEqual(cfg["defaults"]["portfolio_value_usd"], 20_000.0)
            finally:
                os.environ.pop("FORTRESS_RUNTIME_CONFIG", None)
                rc.get_runtime_config(reload=True)

    def test_merge_yaml(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "rt.yaml"
            p.write_text(
                "agents:\n  intraday_sniper:\n    enabled: false\ndefaults:\n  portfolio_value_usd: 7777\n",
                encoding="utf-8",
            )
            os.environ["FORTRESS_RUNTIME_CONFIG"] = str(p)
            try:
                import utils.runtime_config as rc

                rc.get_runtime_config(reload=True)
                self.assertFalse(rc.is_agent_enabled("intraday_sniper"))
                self.assertTrue(rc.is_agent_enabled("daily_screen"))
                self.assertEqual(rc.get_default_portfolio_usd(), 7777.0)
            finally:
                os.environ.pop("FORTRESS_RUNTIME_CONFIG", None)
                rc.get_runtime_config(reload=True)


if __name__ == "__main__":
    unittest.main()
