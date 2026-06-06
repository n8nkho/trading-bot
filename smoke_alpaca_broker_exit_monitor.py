#!/usr/bin/env python3
"""
Smoke test: broker-synced stock positions remain exit-monitor compatible.

The Alpaca sync path writes normalize_alpaca_position() output to
data/positions.json. The stock exit monitor requires an entry timestamp before
it can evaluate time/news/take-profit exits, so this test keeps that schema
contract locked down without live Alpaca/Yahoo calls.
"""

from __future__ import annotations

import sys
from datetime import datetime
from types import ModuleType, SimpleNamespace


def _install_import_stubs() -> None:
    yf_stub = ModuleType("yfinance")
    yf_stub.Ticker = lambda _sym: None
    sys.modules["yfinance"] = yf_stub

    llm_stub = ModuleType("utils.local_llm")
    llm_stub.call_ollama = lambda *_args, **_kwargs: (
        '{"has_negative_news": false, "summary": "stub"}'
    )
    sys.modules["utils.local_llm"] = llm_stub

    screener_stub = ModuleType("agents.screener_agent")
    screener_stub.get_news_headlines = lambda _ticker, limit=5: []
    sys.modules["agents.screener_agent"] = screener_stub

    schema_stub = ModuleType("utils.option_contract_schema")
    schema_stub.normalize_option_position = lambda pos: pos
    sys.modules["utils.option_contract_schema"] = schema_stub


class _FakeClose:
    iloc = [102.0]


class _FakeHistory:
    def __len__(self):
        return 1

    def __getitem__(self, key):
        if key != "Close":
            raise KeyError(key)
        return _FakeClose()


class _FakeTicker:
    def __init__(self, sym):
        self.sym = sym

    def history(self, period="1d", interval="1m"):
        return _FakeHistory()


def main() -> int:
    _install_import_stubs()

    from utils.alpaca_broker import normalize_alpaca_position
    import agents.exit_monitor as exit_monitor

    exit_monitor.yf.Ticker = lambda sym: _FakeTicker(sym)
    exit_monitor.check_negative_news = lambda _ticker: {
        "has_negative_news": False,
        "summary": "stub",
    }

    raw_position = SimpleNamespace(
        symbol="TST",
        qty="10",
        avg_entry_price="100",
        current_price="102",
        unrealized_pl="20",
        cost_basis="1000",
    )
    position = normalize_alpaca_position(raw_position)
    if "shares" not in position and position.get("qty") is not None:
        position["shares"] = position["qty"]

    assert position.get("entry_time"), "broker-normalized positions need entry_time"
    datetime.fromisoformat(position["entry_time"])

    decisions = exit_monitor.monitor_positions([position])
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["action"] == "SELL_50%", decision
    assert "Error during evaluation" not in decision["reason"], decision

    print("[smoke] smoke_alpaca_broker_exit_monitor: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
