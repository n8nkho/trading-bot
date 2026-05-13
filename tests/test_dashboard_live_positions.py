import json
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

            fake_broker = _module("utils.alpaca_broker", fetch_broker_positions=lambda: ([], None))
            fake_yfinance = _module("yfinance")

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
