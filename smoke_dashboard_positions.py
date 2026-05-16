#!/usr/bin/env python3
"""Smoke test for Command Center position source precedence."""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _install_import_stubs() -> None:
    """Provide tiny stubs for optional web/data deps absent in lean CI images."""
    flask = types.ModuleType("flask")

    class _DummyFlask:
        def __init__(self, *args, **kwargs):
            self.config = {}

        def route(self, *args, **kwargs):
            return lambda fn: fn

        def before_request(self, fn):
            return fn

        def run(self, *args, **kwargs):
            return None

    flask.Flask = _DummyFlask
    flask.render_template = lambda *args, **kwargs: ""
    flask.jsonify = lambda obj=None, *args, **kwargs: obj if obj is not None else {}
    flask.make_response = lambda *args, **kwargs: args[0] if args else None
    flask.redirect = lambda *args, **kwargs: None
    flask.url_for = lambda *args, **kwargs: ""
    flask.Response = lambda *args, **kwargs: None
    flask.request = types.SimpleNamespace(
        path="",
        authorization=None,
        headers={},
        args={},
        get_json=lambda *args, **kwargs: {},
        get_data=lambda *args, **kwargs: b"",
    )
    sys.modules.setdefault("flask", flask)

    flask_cors = types.ModuleType("flask_cors")
    flask_cors.CORS = lambda *args, **kwargs: None
    sys.modules.setdefault("flask_cors", flask_cors)

    simple_backtest = types.ModuleType("utils.simple_daily_backtest")
    simple_backtest.read_backtest_snapshot = lambda *args, **kwargs: None
    simple_backtest.run_daily_momentum_backtest = lambda *args, **kwargs: {}
    sys.modules.setdefault("utils.simple_daily_backtest", simple_backtest)

    yfinance = types.ModuleType("yfinance")
    yfinance.download = lambda *args, **kwargs: None
    sys.modules.setdefault("yfinance", yfinance)


def main() -> int:
    _install_import_stubs()

    alpaca_broker = types.ModuleType("utils.alpaca_broker")
    alpaca_broker.fetch_broker_positions = lambda: ([], None)
    sys.modules["utils.alpaca_broker"] = alpaca_broker

    cc = importlib.import_module("dashboard.command_center")

    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td)
        (data_dir / "positions.json").write_text(
            json.dumps(
                [
                    {
                        "ticker": "STALE",
                        "shares": 10,
                        "entry_price": 100,
                        "current_price": 101,
                    }
                ]
            ),
            encoding="utf-8",
        )
        cc.DATA_DIR = data_dir
        out = cc.get_live_positions()

    if out.get("positions") != [] or out.get("count") != 0:
        print("[FAIL] expected broker-empty positions to remain empty, got:", out, file=sys.stderr)
        return 1

    alpaca_broker.fetch_broker_positions = lambda: (None, "alpaca_error")
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td)
        (data_dir / "positions.json").write_text(
            json.dumps(
                [
                    {
                        "ticker": "FALLBACK",
                        "shares": 2,
                        "entry_price": 50,
                        "current_price": 55,
                    }
                ]
            ),
            encoding="utf-8",
        )
        cc.DATA_DIR = data_dir
        out = cc.get_live_positions()

    if out.get("count") != 1 or out.get("positions", [{}])[0].get("ticker") != "FALLBACK":
        print("[FAIL] expected broker failure to fall back to positions.json, got:", out, file=sys.stderr)
        return 1

    print("[OK] broker-empty positions do not fall back to stale positions.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
