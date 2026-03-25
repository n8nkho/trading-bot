#!/usr/bin/env python3
"""
Smoke: SPY intraday swing cycle (shadow, fixture path) + Alpaca paper limit submit + cancel on SPY.
Requires ALPACA keys and paper URL for the Alpaca portion.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


def _fixture_cycle() -> int:
    import pytz
    import pandas as pd
    from agents import spy_intraday_swing as m

    tz = "America/New_York"
    idx = pd.date_range("2024-06-12 09:30", periods=20, freq="5min", tz=tz)
    base = 500.0
    r = pd.Series(range(20), index=idx, dtype=float)
    close = base + r * -0.15 + 2.0
    spy = pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.2,
            "Low": close - 0.2,
            "Close": close,
            "Volume": pd.Series([1_000_000 + i * 5000 for i in range(20)], index=idx, dtype=float),
        },
        index=idx,
    )
    es_idx = pd.date_range("2024-06-12 09:30", periods=20, freq="5min", tz=tz)
    er = pd.Series(range(20), index=es_idx, dtype=float)
    eclose = 5300 + er * 0.5
    es = pd.DataFrame(
        {
            "Open": eclose,
            "High": eclose + 1,
            "Low": eclose - 1,
            "Close": eclose,
            "Volume": pd.Series([50_000 + i * 100 for i in range(20)], index=es_idx, dtype=float),
        },
        index=es_idx,
    )
    et = pytz.timezone("America/New_York")
    now = et.localize(datetime(2024, 6, 12, 11, 0, 0))
    tmp = Path("data") / "_smoke_spy_swing"
    tmp.mkdir(parents=True, exist_ok=True)
    out = m.run_spy_swing_cycle(
        shadow_only=True,
        portfolio_equity=5000.0,
        data_dir=tmp,
        now_et=now,
        spy_df=spy,
        es_df=es,
    )
    for p in tmp.glob("spy_swing_shadow_*.jsonl"):
        p.unlink(missing_ok=True)
    try:
        tmp.rmdir()
    except OSError:
        pass
    if not out.get("ok"):
        print("[FAIL] fixture spy_swing cycle", out, file=sys.stderr)
        return 1
    print("[OK] spy_swing fixture cycle suggested_action=%s" % out.get("suggested_action"))
    return 0


def _alpaca_spy_cancel() -> int:
    load_dotenv()
    key = os.getenv("ALPACA_API_KEY")
    sec = os.getenv("ALPACA_SECRET_KEY")
    base = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    if not key or not sec:
        print("[SKIP] smoke_spy_swing_alpaca: missing ALPACA keys (Alpaca part skipped)")
        return 0
    if "paper" not in base.lower():
        print("[FAIL] ALPACA_BASE_URL must be paper", file=sys.stderr)
        return 1

    import yfinance as yf
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import LimitOrderRequest

    sym = "SPY"
    t = yf.Ticker(sym)
    hist = t.history(period="5d")
    if hist.empty:
        print(f"[FAIL] no yfinance data for {sym}", file=sys.stderr)
        return 1
    last = float(hist["Close"].iloc[-1])
    limit_px = round(max(0.01, last * 0.3), 2)

    from utils.pre_trade_gate import evaluate_pre_trade_submission

    gate = evaluate_pre_trade_submission(
        side="BUY",
        symbol=sym,
        qty=1.0,
        estimated_notional_usd=limit_px,
    )
    if not gate["allowed"]:
        print("[FAIL] pre_trade_gate blocked:", json.dumps(gate), file=sys.stderr)
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
    print(f"[OK] smoke_spy_swing_alpaca SPY limit={limit_px} order_id={oid} cancelled")
    return 0


def main() -> int:
    a = _fixture_cycle()
    if a != 0:
        return a
    return _alpaca_spy_cancel()


if __name__ == "__main__":
    raise SystemExit(main())
