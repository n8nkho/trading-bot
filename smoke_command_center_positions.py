#!/usr/bin/env python3
"""Smoke: Command Center position readers tolerate stale/malformed local files."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

import dashboard.command_center as cc
import utils.alpaca_broker as alpaca_broker


def main() -> int:
    td = Path(tempfile.mkdtemp())
    original_data_dir = cc.DATA_DIR
    original_fetch = alpaca_broker.fetch_broker_positions
    original_assets = cc.require_market_assets
    original_news = cc._fetch_news_for_ticker
    original_yfinance = sys.modules.get("yfinance")
    try:
        data = td / "data"
        data.mkdir()
        cc.DATA_DIR = data
        sys.modules["yfinance"] = types.SimpleNamespace()

        # A successful empty broker response must not fall back to stale local positions.
        (data / "positions.json").write_text(
            json.dumps([{"ticker": "STALE", "qty": 1, "entry_price": 10}]),
            encoding="utf-8",
        )
        alpaca_broker.fetch_broker_positions = lambda: ([], None)
        positions = cc.get_live_positions()
        assert positions["count"] == 0, positions
        assert positions["positions"] == [], positions

        # Malformed positions payloads should not 500 /api/news or block dashboard load.
        (data / "positions.json").write_text('{"positions": null}', encoding="utf-8")
        cc.require_market_assets = lambda: {}
        cc._fetch_news_for_ticker = lambda *_args, **_kwargs: []
        news = cc.get_news_and_impact()
        assert isinstance(news.get("top_10"), list), news

        (data / "positions.json").write_text('"not-a-position-list"', encoding="utf-8")
        assert cc.get_news_and_impact().get("top_10") == []
    finally:
        cc.DATA_DIR = original_data_dir
        alpaca_broker.fetch_broker_positions = original_fetch
        cc.require_market_assets = original_assets
        cc._fetch_news_for_ticker = original_news
        if original_yfinance is None:
            sys.modules.pop("yfinance", None)
        else:
            sys.modules["yfinance"] = original_yfinance
        shutil.rmtree(td, ignore_errors=True)

    print("[OK] smoke_command_center_positions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
