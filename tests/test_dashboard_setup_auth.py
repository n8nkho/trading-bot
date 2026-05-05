import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

simple_daily_backtest = types.ModuleType("utils.simple_daily_backtest")
simple_daily_backtest.read_backtest_snapshot = lambda *args, **kwargs: {}
simple_daily_backtest.run_daily_momentum_backtest = lambda *args, **kwargs: {}
sys.modules.setdefault("utils.simple_daily_backtest", simple_daily_backtest)

import dashboard.command_center as cc


class DashboardSetupAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_env_file = cc.ENV_FILE
        self.old_data_dir = cc.DATA_DIR
        self.old_setup_complete_file = cc.SETUP_COMPLETE_FILE
        self.old_user = os.environ.get("FORTRESS_DASHBOARD_USER")
        self.old_pw = os.environ.get("FORTRESS_DASHBOARD_PASS")
        self.old_alpaca_key = os.environ.get("ALPACA_API_KEY")
        self.old_alpaca_secret = os.environ.get("ALPACA_SECRET_KEY")

        cc.DATA_DIR = self.root / "data"
        cc.ENV_FILE = self.root / ".env"
        cc.SETUP_COMPLETE_FILE = cc.DATA_DIR / "setup_complete"
        os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
        os.environ["FORTRESS_DASHBOARD_PASS"] = "strong-pass"
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_SECRET_KEY", None)

    def tearDown(self):
        cc.ENV_FILE = self.old_env_file
        cc.DATA_DIR = self.old_data_dir
        cc.SETUP_COMPLETE_FILE = self.old_setup_complete_file
        self._restore_env("FORTRESS_DASHBOARD_USER", self.old_user)
        self._restore_env("FORTRESS_DASHBOARD_PASS", self.old_pw)
        self._restore_env("ALPACA_API_KEY", self.old_alpaca_key)
        self._restore_env("ALPACA_SECRET_KEY", self.old_alpaca_secret)
        self.tmp.cleanup()

    @staticmethod
    def _restore_env(key, value):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    def _client(self):
        return cc.app.test_client()

    def _write_existing_keys(self):
        cc.ENV_FILE.write_text(
            "ALPACA_API_KEY=PKEXISTING12345\n"
            "ALPACA_SECRET_KEY=SECRETEXISTING12345\n",
            encoding="utf-8",
        )

    def test_completed_setup_rejects_unauthenticated_key_overwrite(self):
        self._write_existing_keys()
        resp = self._client().post(
            "/api/setup/save_keys",
            json={"api_key": "PKATTACKER12345", "secret_key": "SECRETATTACKER12345"},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertIn("PKEXISTING12345", cc.ENV_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("PKATTACKER12345", cc.ENV_FILE.read_text(encoding="utf-8"))

    def test_completed_setup_allows_authenticated_key_update(self):
        self._write_existing_keys()
        resp = self._client().post(
            "/api/setup/save_keys",
            json={"api_key": "PKROTATED12345", "secret_key": "SECRETROTATED12345"},
            auth=("operator", "strong-pass"),
        )

        self.assertEqual(resp.status_code, 200)
        body = cc.ENV_FILE.read_text(encoding="utf-8")
        self.assertIn("PKROTATED12345", body)
        self.assertIn("SECRETROTATED12345", body)
        self.assertNotIn("PKEXISTING12345", body)

    def test_first_run_still_allows_unauthenticated_key_save(self):
        resp = self._client().post(
            "/api/setup/save_keys",
            json={"api_key": "PKFIRSTRUN12345", "secret_key": "SECRETFIRSTRUN12345"},
        )

        self.assertEqual(resp.status_code, 200)
        body = cc.ENV_FILE.read_text(encoding="utf-8")
        self.assertIn("PKFIRSTRUN12345", body)
        self.assertIn("SECRETFIRSTRUN12345", body)


if __name__ == "__main__":
    unittest.main()
