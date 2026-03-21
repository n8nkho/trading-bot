#!/usr/bin/env python3
"""
End-to-end: Alpaca PAPER limit order submit + immediate cancel (Phase A/B/C gate).
Requires ALPACA_API_KEY / ALPACA_SECRET_KEY and paper URL. Safe: limit far from market.
"""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    key = os.getenv("ALPACA_API_KEY")
    sec = os.getenv("ALPACA_SECRET_KEY")
    base = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    if not key or not sec:
        print("[SKIP] smoke_alpaca_paper_trade_cancel: missing ALPACA keys")
        return 0
    if "paper" not in base.lower():
        print("[FAIL] ALPACA_BASE_URL must be paper", file=sys.stderr)
        return 1

    with open("config/watchlist.json", "r") as f:
        wl = json.load(f).get("quality_stocks") or []
    if not wl:
        print("[FAIL] watchlist empty", file=sys.stderr)
        return 1
    sym = str(wl[0].get("ticker")).strip().upper()

    import yfinance as yf
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import LimitOrderRequest

    t = yf.Ticker(sym)
    hist = t.history(period="5d")
    if hist.empty:
        print(f"[FAIL] no yfinance data for {sym}", file=sys.stderr)
        return 1
    last = float(hist["Close"].iloc[-1])
    # Limit well below last — should not fill before cancel
    limit_px = round(max(0.01, last * 0.3), 2)

    from utils.pre_trade_gate import evaluate_pre_trade_submission

    gate = evaluate_pre_trade_submission(
        side="BUY",
        symbol=sym,
        qty=1.0,
        estimated_notional_usd=limit_px,
    )
    if not gate["allowed"]:
        print("[FAIL] pre_trade_gate blocked:", gate, file=sys.stderr)
        return 1

    client = TradingClient(key, sec, paper=True)
    req = LimitOrderRequest(
        symbol=sym,
        qty=1,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        limit_price=limit_px,
    )
    order = client.submit_order(req)
    oid = str(order.id)
    client.cancel_order_by_id(oid)
    print(f"[OK] smoke_alpaca_paper_trade_cancel sym={sym} limit={limit_px} order_id={oid} cancelled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
