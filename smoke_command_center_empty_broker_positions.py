#!/usr/bin/env python3
"""Smoke: a successful empty Alpaca positions response must not load stale file data."""

from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path


def _install_command_center_import_stubs() -> None:
    flask = types.ModuleType("flask")

    class Flask:
        def __init__(self, *args, **kwargs):
            self.config = {}

        def before_request(self, func):
            return func

        def route(self, *args, **kwargs):
            return lambda func: func

        def errorhandler(self, *args, **kwargs):
            return lambda func: func

    flask.Flask = Flask
    flask.render_template = lambda *args, **kwargs: ""
    flask.jsonify = lambda value=None, *args, **kwargs: value if value is not None else kwargs
    flask.make_response = lambda *args, **kwargs: None
    flask.request = types.SimpleNamespace(path="", authorization=None, method="GET", headers={}, args={})
    flask.redirect = lambda *args, **kwargs: None
    flask.url_for = lambda *args, **kwargs: ""
    flask.Response = lambda *args, **kwargs: None
    sys.modules["flask"] = flask

    flask_cors = types.ModuleType("flask_cors")
    flask_cors.CORS = lambda app: app
    sys.modules["flask_cors"] = flask_cors

    drift_detector = types.ModuleType("agents.drift_detector")
    drift_detector.analyze_drift = lambda *args, **kwargs: {}
    sys.modules["agents.drift_detector"] = drift_detector

    simple_daily_backtest = types.ModuleType("utils.simple_daily_backtest")
    simple_daily_backtest.read_backtest_snapshot = lambda *args, **kwargs: {}
    simple_daily_backtest.run_daily_momentum_backtest = lambda *args, **kwargs: {}
    sys.modules["utils.simple_daily_backtest"] = simple_daily_backtest

    yfinance = types.ModuleType("yfinance")
    yfinance.download = lambda *args, **kwargs: None
    yfinance.Ticker = lambda *args, **kwargs: types.SimpleNamespace(history=lambda *a, **k: None)
    sys.modules["yfinance"] = yfinance


def main() -> int:
    _install_command_center_import_stubs()

    import dashboard.command_center as cc
    import utils.alpaca_broker as alpaca_broker

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "positions.json").write_text(
            '[{"ticker":"STALE","qty":10,"entry_price":100,"current_price":101}]',
            encoding="utf-8",
        )
        cc.DATA_DIR = data_dir
        alpaca_broker.fetch_broker_positions = lambda: ([], None)

        result = cc.get_live_positions()

    assert result["positions"] == [], result
    assert result["count"] == 0, result
    print("[smoke] smoke_command_center_empty_broker_positions: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
