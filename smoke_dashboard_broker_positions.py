#!/usr/bin/env python3
"""
Smoke test dashboard broker-position semantics:
- a successful empty broker response must not fall back to stale positions.json
- fetch_broker_positions accepts the APCA_* credential names used by other agents
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path


def _install_dashboard_import_stubs() -> None:
    """Keep this smoke focused on dashboard position logic in minimal envs."""
    flask = types.ModuleType("flask")

    class FakeFlask:
        def __init__(self, *args, **kwargs):
            self.config = {}

        def route(self, *args, **kwargs):
            return lambda func: func

        def before_request(self, func):
            return func

        def run(self, *args, **kwargs):
            return None

    class FakeResponse:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    flask.Flask = FakeFlask
    flask.render_template = lambda *args, **kwargs: ""
    flask.jsonify = lambda obj=None, *args, **kwargs: obj if obj is not None else {}
    flask.make_response = lambda *args, **kwargs: args[0] if args else None
    flask.request = types.SimpleNamespace(path="", authorization=None, args={}, json=None)
    flask.redirect = lambda *args, **kwargs: None
    flask.url_for = lambda endpoint, **kwargs: endpoint
    flask.Response = FakeResponse
    sys.modules.setdefault("flask", flask)

    flask_cors = types.ModuleType("flask_cors")
    flask_cors.CORS = lambda *args, **kwargs: None
    sys.modules.setdefault("flask_cors", flask_cors)


def _install_fake_yfinance() -> None:
    yf = types.ModuleType("yfinance")
    yf.download = lambda *args, **kwargs: None
    sys.modules["yfinance"] = yf


def _install_fake_alpaca() -> list[tuple[str, str, bool]]:
    calls: list[tuple[str, str, bool]] = []

    class FakePosition:
        symbol = "MSFT"
        qty = "2"
        avg_entry_price = "100"
        current_price = "110"
        unrealized_pl = "20"
        cost_basis = "200"

    class FakeTradingClient:
        def __init__(self, key: str, secret: str, paper: bool = True):
            calls.append((key, secret, paper))

        def get_all_positions(self):
            return [FakePosition()]

    alpaca = types.ModuleType("alpaca")
    trading = types.ModuleType("alpaca.trading")
    client = types.ModuleType("alpaca.trading.client")
    client.TradingClient = FakeTradingClient
    sys.modules["alpaca"] = alpaca
    sys.modules["alpaca.trading"] = trading
    sys.modules["alpaca.trading.client"] = client
    return calls


def test_dashboard_empty_broker_positions_do_not_fallback() -> None:
    _install_dashboard_import_stubs()
    _install_fake_yfinance()

    import dashboard.command_center as cc
    import utils.alpaca_broker as broker

    original_data_dir = cc.DATA_DIR
    original_fetch = broker.fetch_broker_positions
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "positions.json").write_text(
                json.dumps([{"ticker": "AAPL", "qty": 5, "entry_price": 150}]),
                encoding="utf-8",
            )
            cc.DATA_DIR = data_dir
            broker.fetch_broker_positions = lambda: ([], None)

            result = cc.get_live_positions()

            assert result["positions"] == [], result
            assert result["count"] == 0, result
    finally:
        cc.DATA_DIR = original_data_dir
        broker.fetch_broker_positions = original_fetch


def test_dashboard_falls_back_when_broker_fetch_fails() -> None:
    _install_dashboard_import_stubs()
    _install_fake_yfinance()

    import dashboard.command_center as cc
    import utils.alpaca_broker as broker

    original_data_dir = cc.DATA_DIR
    original_fetch = broker.fetch_broker_positions
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "positions.json").write_text(
                json.dumps([{"ticker": "AAPL", "qty": 5, "entry_price": 150}]),
                encoding="utf-8",
            )
            cc.DATA_DIR = data_dir
            broker.fetch_broker_positions = lambda: (None, "missing_alpaca_keys")

            result = cc.get_live_positions()

            assert result["count"] == 1, result
            assert result["positions"][0]["ticker"] == "AAPL", result
    finally:
        cc.DATA_DIR = original_data_dir
        broker.fetch_broker_positions = original_fetch


def test_fetch_broker_positions_accepts_apca_credentials() -> None:
    calls = _install_fake_alpaca()

    import utils.alpaca_broker as broker

    old_env = {
        name: os.environ.get(name)
        for name in (
            "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY",
            "APCA_API_KEY_ID",
            "APCA_API_SECRET_KEY",
            "ALPACA_BASE_URL",
        )
    }
    try:
        for name in old_env:
            os.environ.pop(name, None)
        os.environ["APCA_API_KEY_ID"] = "apca_key"
        os.environ["APCA_API_SECRET_KEY"] = "apca_secret"

        positions, err = broker.fetch_broker_positions()

        assert err is None, err
        assert positions and positions[0]["ticker"] == "MSFT", positions
        assert calls == [("apca_key", "apca_secret", True)], calls
    finally:
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    test_dashboard_empty_broker_positions_do_not_fallback()
    test_dashboard_falls_back_when_broker_fetch_fails()
    test_fetch_broker_positions_accepts_apca_credentials()
    print("[smoke] smoke_dashboard_broker_positions: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
