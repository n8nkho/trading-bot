#!/usr/bin/env python3
"""Smoke: /api/chart_bars parses yfinance download MultiIndex fallback rows."""
from __future__ import annotations

import sys
import types


def _install_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


class _FakeFlask:
    def __init__(self, *args, **kwargs):
        self.config = {}

    def before_request(self, fn):
        return fn

    def route(self, *args, **kwargs):
        def _decorator(fn):
            return fn

        return _decorator

    def run(self, *args, **kwargs):
        return None


def _install_import_stubs() -> None:
    request = types.SimpleNamespace(
        path="/",
        method="GET",
        authorization=None,
        headers={},
        args={},
        get_json=lambda *args, **kwargs: {},
        data=b"",
    )
    _install_module(
        "flask",
        Flask=_FakeFlask,
        render_template=lambda *args, **kwargs: "",
        jsonify=lambda payload=None, *args, **kwargs: payload if payload is not None else kwargs,
        make_response=lambda payload="", *args, **kwargs: types.SimpleNamespace(data=payload, headers={}),
        request=request,
        redirect=lambda *args, **kwargs: "",
        url_for=lambda *args, **kwargs: "",
        Response=object,
    )
    _install_module("flask_cors", CORS=lambda app: None)
    _install_module("utils.market_assets", require_market_assets=lambda *args, **kwargs: {})
    _install_module("utils.policy_profile", get_profile_bundle=lambda *args, **kwargs: {})
    _install_module(
        "utils.trust_ledger",
        append_trust_event=lambda *args, **kwargs: None,
        enrich_trust_ledger_items=lambda items, *args, **kwargs: items,
        read_recent_trust_events=lambda *args, **kwargs: [],
    )
    _install_module(
        "utils.operator_halt",
        get_halt_state=lambda *args, **kwargs: {"halted": False},
        set_trading_halt=lambda *args, **kwargs: {"halted": False},
    )
    _install_module("utils.alerts", send_operator_alert=lambda *args, **kwargs: None)
    _install_module(
        "utils.simple_daily_backtest",
        read_backtest_snapshot=lambda *args, **kwargs: {},
        run_daily_momentum_backtest=lambda *args, **kwargs: {},
    )
    _install_module("utils.run_registry", summarize_screening_runs=lambda *args, **kwargs: {})
    _install_module("agents.drift_detector", analyze_drift=lambda *args, **kwargs: {})
    _install_module("utils.alpaca_env", is_alpaca_paper=lambda *args, **kwargs: True)


class _FakeDate:
    def __init__(self, value: str):
        self._value = value

    def strftime(self, fmt: str) -> str:
        return self._value


class _FakeRow:
    def __init__(self, values):
        self._values = values
        self.index = list(values)

    def __getitem__(self, key):
        if key not in self._values:
            raise KeyError(key)
        return self._values[key]


class _FakeFrame:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.empty = not self._rows

    def iterrows(self):
        return iter(self._rows)


class _FakeTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol

    def history(self, **kwargs):
        return _FakeFrame()


def _fake_download(symbol: str, **kwargs):
    assert symbol == "SPY"
    return _FakeFrame(
        [
            (
                _FakeDate("2026-05-28"),
                _FakeRow(
                    {
                        ("Open", "SPY"): 520.12345,
                        ("High", "SPY"): 525.98765,
                        ("Low", "SPY"): 518.11111,
                        ("Close", "SPY"): 524.22229,
                        ("Volume", "SPY"): 1234567.0,
                    }
                ),
            )
        ]
    )


def main() -> int:
    _install_import_stubs()
    _install_module("yfinance", Ticker=_FakeTicker, download=_fake_download)

    from dashboard.command_center import get_chart_bars_json

    payload = get_chart_bars_json("spy", 120)
    assert payload["ticker"] == "SPY"
    assert payload["bars"] == [
        {
            "time": "2026-05-28",
            "open": 520.1235,
            "high": 525.9877,
            "low": 518.1111,
            "close": 524.2223,
            "volume": 1234567,
        }
    ]

    print("[OK] smoke_chart_bars_yfinance_multiindex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
