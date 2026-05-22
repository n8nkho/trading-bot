#!/usr/bin/env python3
"""
Smoke: dashboard /api/positions must honor an empty successful Alpaca broker response.

Regression guard for the broker-truth path: an empty list means the broker account is
flat, not that the dashboard should fall back to stale data/positions.json.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_optional_import_stubs() -> None:
    """Keep this smoke focused when the local automation image lacks dashboard deps."""
    if "flask" not in sys.modules:
        try:
            __import__("flask")
        except ImportError:
            flask = types.ModuleType("flask")

            class DummyFlask:
                def __init__(self, *args, **kwargs):
                    self.config = {}

                def before_request(self, fn):
                    return fn

                def route(self, *args, **kwargs):
                    return lambda fn: fn

                def run(self, *args, **kwargs):
                    return None

            flask.Flask = DummyFlask
            flask.render_template = lambda *args, **kwargs: ""
            flask.jsonify = lambda obj=None, *args, **kwargs: obj if obj is not None else kwargs
            flask.make_response = lambda obj=None, *args, **kwargs: obj
            flask.request = types.SimpleNamespace(args={}, headers={}, authorization=None, path="/")
            flask.redirect = lambda *args, **kwargs: ""
            flask.url_for = lambda endpoint, **kwargs: endpoint
            flask.Response = object
            sys.modules["flask"] = flask

    if "flask_cors" not in sys.modules:
        try:
            __import__("flask_cors")
        except ImportError:
            flask_cors = types.ModuleType("flask_cors")
            flask_cors.CORS = lambda *args, **kwargs: None
            sys.modules["flask_cors"] = flask_cors

    if "yfinance" not in sys.modules:
        yf = types.ModuleType("yfinance")
        yf.download = lambda *args, **kwargs: None
        yf.Ticker = lambda *args, **kwargs: types.SimpleNamespace(history=lambda *a, **k: None)
        sys.modules["yfinance"] = yf


def main() -> int:
    _install_optional_import_stubs()

    import dashboard.command_center as cc
    import utils.alpaca_broker as broker

    original_fetch = broker.fetch_broker_positions
    original_read_json = cc._read_json
    broker.fetch_broker_positions = lambda: ([], None)
    cc._read_json = lambda path, default=None: [
        {"ticker": "STALE", "qty": 10, "entry_price": 100, "current_price": 99}
    ]
    try:
        result = cc.get_live_positions()
    finally:
        broker.fetch_broker_positions = original_fetch
        cc._read_json = original_read_json

    if result.get("positions") != [] or result.get("count") != 0:
        print("[FAIL] expected broker-empty result to suppress stale fallback:", result, file=sys.stderr)
        return 1
    print("[OK] broker-empty positions returns flat dashboard state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
