#!/usr/bin/env python3
"""Smoke: TradingView webhook queue append + read (temp file)."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import utils.tradingview_webhook as tv


def main() -> int:
    os.environ.pop("FORTRESS_TV_WEBHOOK_SECRET", None)
    td = Path(tempfile.mkdtemp())
    try:
        tv.QUEUE_PATH = td / "tradingview_signal_queue.jsonl"
        assert tv.verify_webhook_secret(None, None) is True
        assert tv.verify_webhook_secret("x", None) is True  # no secret configured

        row = tv.append_tradingview_event(
            raw_body=b'{"ticker":"AAPL","side":"buy"}',
            content_type="application/json",
            remote_addr="127.0.0.1",
            query_params={},
        )
        assert row.get("ticker_guess") == "AAPL"
        assert row.get("parse_kind") == "json"

        tv.append_tradingview_event(
            raw_body=b"MSFT alert plain",
            content_type="text/plain",
            remote_addr="127.0.0.1",
            query_params={},
        )

        items = tv.read_recent_signals(10)
        assert len(items) == 2

        os.environ["FORTRESS_TV_WEBHOOK_SECRET"] = "abc"
        assert tv.verify_webhook_secret("abc", None) is True
        assert tv.verify_webhook_secret("wrong", None) is False
        assert tv.verify_webhook_secret(None, "abc") is True
    finally:
        shutil.rmtree(td, ignore_errors=True)
        os.environ.pop("FORTRESS_TV_WEBHOOK_SECRET", None)

    print("[OK] smoke_tradingview_webhook")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
