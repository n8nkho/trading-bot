import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def _install_command_center_import_stubs():
    fake_cors = _module("flask_cors", CORS=lambda app, *args, **kwargs: app)
    module_stubs = {
        "flask_cors": fake_cors,
        "utils.market_assets": _module("utils.market_assets", require_market_assets=lambda: {}),
        "utils.policy_profile": _module("utils.policy_profile", get_profile_bundle=lambda: {}),
        "utils.trust_ledger": _module(
            "utils.trust_ledger",
            append_trust_event=lambda *args, **kwargs: None,
            enrich_trust_ledger_items=lambda items: items,
            read_recent_trust_events=lambda *args, **kwargs: [],
        ),
        "utils.operator_halt": _module(
            "utils.operator_halt",
            get_halt_state=lambda: {"effective_halted": False},
            set_trading_halt=lambda *args, **kwargs: {"ok": True},
        ),
        "utils.alerts": _module("utils.alerts", send_operator_alert=lambda *args, **kwargs: None),
        "utils.simple_daily_backtest": _module(
            "utils.simple_daily_backtest",
            read_backtest_snapshot=lambda *args, **kwargs: {},
            run_daily_momentum_backtest=lambda *args, **kwargs: {},
        ),
        "utils.run_registry": _module("utils.run_registry", summarize_screening_runs=lambda *args, **kwargs: []),
        "agents.drift_detector": _module("agents.drift_detector", analyze_drift=lambda *args, **kwargs: {}),
        "utils.alpaca_env": _module("utils.alpaca_env", is_alpaca_paper=lambda: True),
    }
    return patch.dict(sys.modules, module_stubs)


def _load_command_center():
    sys.modules.pop("dashboard.command_center", None)
    with _install_command_center_import_stubs():
        import dashboard.command_center as command_center
    return command_center


class DashboardSetupAuthTest(unittest.TestCase):
    def setUp(self):
        self.cc = _load_command_center()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_env_file = self.cc.ENV_FILE
        self.old_data_dir = self.cc.DATA_DIR
        self.old_setup_complete_file = self.cc.SETUP_COMPLETE_FILE
        self.old_user = os.environ.get("FORTRESS_DASHBOARD_USER")
        self.old_pw = os.environ.get("FORTRESS_DASHBOARD_PASS")
        self.old_alpaca_key = os.environ.get("ALPACA_API_KEY")
        self.old_alpaca_secret = os.environ.get("ALPACA_SECRET_KEY")

        self.cc.DATA_DIR = self.root / "data"
        self.cc.ENV_FILE = self.root / ".env"
        self.cc.SETUP_COMPLETE_FILE = self.cc.DATA_DIR / "setup_complete"
        os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
        os.environ["FORTRESS_DASHBOARD_PASS"] = "strong-pass"
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_SECRET_KEY", None)

    def tearDown(self):
        self.cc.ENV_FILE = self.old_env_file
        self.cc.DATA_DIR = self.old_data_dir
        self.cc.SETUP_COMPLETE_FILE = self.old_setup_complete_file
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

    def _write_existing_keys(self):
        self.cc.ENV_FILE.write_text(
            "ALPACA_API_KEY=PKEXISTING12345\n"
            "ALPACA_SECRET_KEY=SECRETEXISTING12345\n",
            encoding="utf-8",
        )

    def test_completed_setup_rejects_unauthenticated_key_overwrite(self):
        self._write_existing_keys()

        resp = self.cc.app.test_client().post(
            "/api/setup/save_keys",
            json={"api_key": "PKATTACKER12345", "secret_key": "SECRETATTACKER12345"},
        )

        body = self.cc.ENV_FILE.read_text(encoding="utf-8")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("PKEXISTING12345", body)
        self.assertNotIn("PKATTACKER12345", body)

    def test_completed_setup_allows_authenticated_key_update(self):
        self._write_existing_keys()

        resp = self.cc.app.test_client().post(
            "/api/setup/save_keys",
            json={"api_key": "PKROTATED12345", "secret_key": "SECRETROTATED12345"},
            auth=("operator", "strong-pass"),
        )

        body = self.cc.ENV_FILE.read_text(encoding="utf-8")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("PKROTATED12345", body)
        self.assertIn("SECRETROTATED12345", body)
        self.assertNotIn("PKEXISTING12345", body)

    def test_first_run_still_allows_unauthenticated_key_save(self):
        resp = self.cc.app.test_client().post(
            "/api/setup/save_keys",
            json={"api_key": "PKFIRSTRUN12345", "secret_key": "SECRETFIRSTRUN12345"},
        )

        body = self.cc.ENV_FILE.read_text(encoding="utf-8")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("PKFIRSTRUN12345", body)
        self.assertIn("SECRETFIRSTRUN12345", body)


if __name__ == "__main__":
    unittest.main()
