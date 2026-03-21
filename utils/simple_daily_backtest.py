"""
Lightweight daily-bar momentum sanity backtest (exploration / operator UX — not production alpha).
Writes data/backtest_snapshot.json for dashboard + research panel.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "data" / "backtest_snapshot.json"


def run_daily_momentum_backtest(
    ticker: str,
    *,
    days: int = 252,
    short_window: int = 10,
    long_window: int = 30,
) -> dict:
    import yfinance as yf

    t = yf.Ticker(ticker.strip().upper())
    hist = t.history(period=f"{max(days, 60)}d", interval="1d", auto_adjust=True)
    if hist is None or hist.empty or len(hist) < long_window + 5:
        return {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "error": "insufficient_history",
            "bars": int(len(hist) if hist is not None else 0),
        }

    close = hist["Close"].astype(float)
    sma_s = close.rolling(short_window).mean()
    sma_l = close.rolling(long_window).mean()
    signal = (sma_s > sma_l).astype(int)
    pos = signal.shift(1).fillna(0)
    rets = close.pct_change()
    strat_rets = pos * rets
    eq = (1 + strat_rets.fillna(0)).cumprod()
    total_return = float(eq.iloc[-1] - 1.0)
    dd = float((eq / eq.cummax() - 1).min())
    bh = (1 + rets.fillna(0)).cumprod()
    bh_ret = float(bh.iloc[-1] - 1.0)

    trades = int((pos.diff().fillna(0).abs() > 0).sum())

    out = {
        "timestamp": datetime.now().isoformat(),
        "ticker": ticker.strip().upper(),
        "bars": len(close),
        "strategy_total_return": round(total_return, 4),
        "buy_hold_total_return": round(bh_ret, 4),
        "max_drawdown": round(dd, 4),
        "approx_trades": trades,
        "short_window": short_window,
        "long_window": long_window,
        "note": "Simple SMA crossover on daily bars — illustrative only.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return out


def read_backtest_snapshot() -> dict:
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}
