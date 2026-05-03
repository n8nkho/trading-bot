import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _install_dashboard_import_stubs():
    flask = types.ModuleType("flask")

    class _DummyFlask:
        config = {}

        def __init__(self, *args, **kwargs):
            self.config = {}

        def before_request(self, func):
            return func

        def route(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    flask.Flask = _DummyFlask
    flask.render_template = lambda *args, **kwargs: ""
    flask.jsonify = lambda obj=None, *args, **kwargs: obj if obj is not None else {}
    flask.make_response = lambda obj=None, *args, **kwargs: obj
    flask.request = types.SimpleNamespace(path="", authorization=None, headers={}, args={})
    flask.redirect = lambda *args, **kwargs: ""
    flask.url_for = lambda endpoint, *args, **kwargs: endpoint
    flask.Response = lambda *args, **kwargs: None
    sys.modules.setdefault("flask", flask)

    flask_cors = types.ModuleType("flask_cors")
    flask_cors.CORS = lambda *args, **kwargs: None
    sys.modules.setdefault("flask_cors", flask_cors)

    stubs = {
        "utils.market_assets": {"require_market_assets": lambda: {"market_headline_tickers": []}},
        "utils.policy_profile": {"get_profile_bundle": lambda: {"active_profile": "balanced"}},
        "utils.trust_ledger": {
            "append_trust_event": lambda *args, **kwargs: None,
            "enrich_trust_ledger_items": lambda items: items,
            "read_recent_trust_events": lambda limit=10: [],
        },
        "utils.operator_halt": {
            "get_halt_state": lambda: {"effective_halted": False},
            "set_trading_halt": lambda *args, **kwargs: {},
        },
        "utils.alerts": {"send_operator_alert": lambda *args, **kwargs: None},
        "utils.simple_daily_backtest": {
            "read_backtest_snapshot": lambda *args, **kwargs: {},
            "run_daily_momentum_backtest": lambda *args, **kwargs: {},
        },
        "utils.run_registry": {"summarize_screening_runs": lambda: []},
        "agents.drift_detector": {"analyze_drift": lambda: {}},
        "utils.alpaca_env": {"is_alpaca_paper": lambda: True},
    }
    for name, attrs in stubs.items():
        mod = types.ModuleType(name)
        for attr_name, value in attrs.items():
            setattr(mod, attr_name, value)
        sys.modules.setdefault(name, mod)


_install_dashboard_import_stubs()
import dashboard.command_center as command_center


class HeadlineEventStatusTest(unittest.TestCase):
    def test_status_reads_latest_rows_from_bounded_tail(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            events_path = data_dir / "headline_events.jsonl"
            shadow_path = data_dir / "headline_event_shadow_20990101.jsonl"

            with events_path.open("w", encoding="utf-8") as f:
                for i in range(150):
                    f.write(json.dumps({"event_id": f"ev-{i}", "title": f"title-{i}"}) + "\n")
            with shadow_path.open("w", encoding="utf-8") as f:
                for i in range(30):
                    f.write(json.dumps({"ticker": f"T{i}", "horizon": "5d", "suggested_action": "watch"}) + "\n")

            with patch.object(command_center, "DATA_DIR", data_dir):
                command_center._HEADLINE_STATUS_COUNT_CACHE.clear()
                status = command_center.get_headline_event_status()

            self.assertEqual(status["events_line_count"], 150)
            self.assertEqual(status["last_event"]["event_id"], "ev-149")
            self.assertEqual(len(status["shadow_preview"]), 12)
            self.assertEqual(status["shadow_preview"][0]["ticker"], "T18")
            self.assertEqual(status["shadow_preview"][-1]["ticker"], "T29")

    def test_tail_nonempty_lines_drops_partial_first_line(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            with path.open("w", encoding="utf-8") as f:
                for i in range(20):
                    f.write(json.dumps({"idx": i, "padding": "x" * 40}) + "\n")

            lines = command_center._tail_nonempty_lines(path, limit=3, max_bytes=260)

            self.assertEqual([json.loads(line)["idx"] for line in lines], [17, 18, 19])


if __name__ == "__main__":
    unittest.main()
