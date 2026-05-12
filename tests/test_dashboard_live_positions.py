import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _install_command_center_import_stubs():
    fake_flask = types.ModuleType("flask")

    class FakeFlask:
        def __init__(self, *args, **kwargs):
            self.config = {}

        def before_request(self, func):
            return func

        def route(self, *args, **kwargs):
            return lambda func: func

    fake_flask.Flask = FakeFlask
    fake_flask.render_template = lambda *args, **kwargs: ""
    fake_flask.jsonify = lambda obj=None, *args, **kwargs: obj
    fake_flask.make_response = lambda *args, **kwargs: args[0] if args else None
    fake_flask.request = types.SimpleNamespace(path="", authorization=None, headers={})
    fake_flask.redirect = lambda *args, **kwargs: None
    fake_flask.url_for = lambda *args, **kwargs: ""
    fake_flask.Response = lambda *args, **kwargs: None

    fake_cors = types.ModuleType("flask_cors")
    fake_cors.CORS = lambda app, *args, **kwargs: app

    module_stubs = {
        "flask": fake_flask,
        "flask_cors": fake_cors,
        "utils.market_assets": types.SimpleNamespace(require_market_assets=lambda: {}),
        "utils.policy_profile": types.SimpleNamespace(get_profile_bundle=lambda: {}),
        "utils.trust_ledger": types.SimpleNamespace(
            append_trust_event=lambda *args, **kwargs: None,
            enrich_trust_ledger_items=lambda items: items,
            read_recent_trust_events=lambda *args, **kwargs: [],
        ),
        "utils.operator_halt": types.SimpleNamespace(
            get_halt_state=lambda: {"effective_halted": False},
            set_trading_halt=lambda *args, **kwargs: {"ok": True},
        ),
        "utils.alerts": types.SimpleNamespace(send_operator_alert=lambda *args, **kwargs: None),
        "utils.simple_daily_backtest": types.SimpleNamespace(
            read_backtest_snapshot=lambda *args, **kwargs: {},
            run_daily_momentum_backtest=lambda *args, **kwargs: {},
        ),
        "utils.run_registry": types.SimpleNamespace(summarize_screening_runs=lambda *args, **kwargs: []),
        "agents.drift_detector": types.SimpleNamespace(analyze_drift=lambda *args, **kwargs: {}),
        "utils.alpaca_env": types.SimpleNamespace(is_alpaca_paper=lambda: True),
    }
    return patch.dict(sys.modules, module_stubs)


class DashboardLivePositionsTest(unittest.TestCase):
    def test_empty_broker_positions_do_not_fall_back_to_stale_file(self):
        sys.modules.pop("dashboard.command_center", None)
        with _install_command_center_import_stubs():
            import dashboard.command_center as command_center

            with tempfile.TemporaryDirectory() as td:
                data_dir = Path(td)
                (data_dir / "positions.json").write_text(
                    json.dumps(
                        [
                            {
                                "ticker": "AAPL",
                                "qty": 10,
                                "entry_price": 100,
                                "current_price": 110,
                            }
                        ]
                    ),
                    encoding="utf-8",
                )

                fake_broker = types.ModuleType("utils.alpaca_broker")
                fake_broker.fetch_broker_positions = lambda: ([], None)
                fake_yfinance = types.ModuleType("yfinance")

                original_data_dir = command_center.DATA_DIR
                command_center.DATA_DIR = data_dir
                try:
                    with patch.dict(
                        sys.modules,
                        {"utils.alpaca_broker": fake_broker, "yfinance": fake_yfinance},
                    ):
                        result = command_center.get_live_positions()
                finally:
                    command_center.DATA_DIR = original_data_dir

        self.assertEqual(result["positions"], [])
        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()
