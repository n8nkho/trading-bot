#!/usr/bin/env python3
"""
Historical screener backtest: apply current drop/RSI/volume filters to past dates,
simulate outcomes (stop/target) over N days. Read-only; no live data writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"

# Default params (match screener_agent defaults)
DEFAULT_STOP_PCT = -4.0
DEFAULT_TARGET_PCT = 5.0
HOLD_DAYS = 5


def _load_params():
    """Load current_params or defaults."""
    p = DATA_DIR / "current_params.json"
    if p.exists():
        try:
            with open(p) as f:
                data = json.load(f)
            return {
                "drop_min": data.get("drop_min", -15),
                "drop_max": data.get("drop_max", -5),
                "rsi_threshold": data.get("rsi_threshold", 40),
                "volume_ratio_min": data.get("volume_ratio_min", 1.5),
                "stop_loss_pct": data.get("stop_loss_pct", -2.0),
                "take_profit_pct": data.get("take_profit_pct", 5.0),
            }
        except Exception:
            pass
    return {
        "drop_min": -15,
        "drop_max": -5,
        "rsi_threshold": 40,
        "volume_ratio_min": 1.5,
        "stop_loss_pct": -2.0,
        "take_profit_pct": 5.0,
    }


def _get_watchlist_tickers():
    """Return list of tickers to backtest (base watchlist only for reproducibility)."""
    path = CONFIG_DIR / "watchlist.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        base = data.get("quality_stocks", [])
        out = []
        for s in base:
            t = s.get("ticker") if isinstance(s, dict) else s
            if t:
                out.append(str(t).strip().upper())
        return out
    except Exception:
        return []


def _rsi(series, n=14):
    """RSI from close series (series is iterable of floats)."""
    import pandas as pd
    delta = pd.Series(series).diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=n - 1, min_periods=n).mean()
    avg_loss = loss.ewm(com=n - 1, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if len(rsi) else 50.0


def _check_outcome(ticker: str, as_of_date: datetime, entry_price: float, stop_pct: float, target_pct: float):
    """Fetch forward prices and return outcome: stop_hit, target_hit, or open."""
    try:
        import yfinance as yf
        start = as_of_date.strftime("%Y-%m-%d")
        end = (as_of_date + timedelta(days=HOLD_DAYS + 2)).strftime("%Y-%m-%d")
        hist = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
        if hist is None or getattr(hist, "empty", True) or len(hist) < 2:
            return None
        hist = hist.sort_index()
        lows = hist["Low"]
        closes = hist["Close"]
        for i in range(1, min(len(hist), HOLD_DAYS + 1)):
            low = float(lows.iloc[i])
            close = float(closes.iloc[i])
            pct = (close - entry_price) / entry_price * 100.0
            drawdown = (low - entry_price) / entry_price * 100.0
            if drawdown <= stop_pct:
                return {"outcome": "stop_hit", "pct": pct}
            if pct >= target_pct:
                return {"outcome": "target_hit", "pct": pct}
        last_close = float(closes.iloc[-1])
        pct = (last_close - entry_price) / entry_price * 100.0
        return {"outcome": "open", "pct": pct}
    except Exception:
        return None


def run_screener_backtest(
    start_date: datetime,
    end_date: datetime,
    tickers: list[str] | None = None,
    max_tickers: int = 50,
) -> dict:
    """Run historical screener logic and outcome simulation."""
    import yfinance as yf

    tickers = tickers or _get_watchlist_tickers()
    if not tickers:
        return {
            "error": "No watchlist tickers",
            "trades": 0,
            "win_rate": 0.0,
            "avg_pct": 0.0,
            "max_drawdown_pct": 0.0,
        }
    tickers = tickers[:max_tickers]
    params = _load_params()
    stop_pct = params.get("stop_loss_pct", DEFAULT_STOP_PCT)
    target_pct = params.get("take_profit_pct", DEFAULT_TARGET_PCT)
    drop_min = params.get("drop_min", -15)
    drop_max = params.get("drop_max", -5)
    rsi_threshold = params.get("rsi_threshold", 40)
    vol_min = params.get("volume_ratio_min", 1.5)

    results = []
    current = start_date
    while current <= end_date:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        for ticker in tickers:
            try:
                start = (current - timedelta(days=35)).strftime("%Y-%m-%d")
                end = (current + timedelta(days=1)).strftime("%Y-%m-%d")
                hist = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
                if hist is None or len(hist) < 20:
                    continue
                hist = hist.sort_index()
                row = hist.iloc[-1]
                prev = hist.iloc[-2]
                open_p = float(row["Open"])
                close_p = float(row["Close"])
                vol = float(row["Volume"])
                drop_pct = (open_p - close_p) / open_p * 100.0 if open_p else 0
                mean_vol = hist["Volume"].mean()
                vol_ratio = (vol / mean_vol) if mean_vol else 0
                rsi = _rsi(hist["Close"].tolist(), 14)
                if not (drop_min <= drop_pct <= drop_max):
                    continue
                if rsi >= rsi_threshold:
                    continue
                if vol_ratio < vol_min:
                    continue
                outcome = _check_outcome(ticker, current, close_p, stop_pct, target_pct)
                if outcome:
                    results.append({
                        "ticker": ticker,
                        "date": current.strftime("%Y-%m-%d"),
                        "entry": close_p,
                        "outcome": outcome["outcome"],
                        "pct": round(outcome["pct"], 2),
                    })
            except Exception:
                continue
        current += timedelta(days=1)

    if not results:
        return {
            "start": start_date.strftime("%Y-%m-%d"),
            "end": end_date.strftime("%Y-%m-%d"),
            "trades": 0,
            "win_rate": 0.0,
            "avg_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sample": [],
        }
    wins = sum(1 for r in results if r["outcome"] == "target_hit")
    stops = sum(1 for r in results if r["outcome"] == "stop_hit")
    win_rate = wins / len(results) * 100.0
    avg_pct = sum(r["pct"] for r in results) / len(results)
    pcts = [r["pct"] for r in results]
    cummin = 0.0
    cum = 0.0
    max_dd = 0.0
    for p in pcts:
        cum += p
        cummin = min(cummin, cum)
        max_dd = min(max_dd, cum - cummin)
    return {
        "start": start_date.strftime("%Y-%m-%d"),
        "end": end_date.strftime("%Y-%m-%d"),
        "trades": len(results),
        "wins": wins,
        "stops": stops,
        "win_rate": round(win_rate, 2),
        "avg_pct": round(avg_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "params": params,
        "sample": results[:15],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Historical screener backtest (read-only).")
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=30, help="Lookback days if --start/--end not set")
    parser.add_argument("--max-tickers", type=int, default=50, help="Max tickers to backtest")
    args = parser.parse_args()
    end = datetime.now()
    if args.end:
        try:
            end = datetime.strptime(args.end, "%Y-%m-%d")
        except ValueError:
            print("Invalid --end date; use YYYY-MM-DD", file=sys.stderr)
            return 1
    if args.start:
        try:
            start = datetime.strptime(args.start, "%Y-%m-%d")
        except ValueError:
            print("Invalid --start date; use YYYY-MM-DD", file=sys.stderr)
            return 1
    else:
        start = end - timedelta(days=args.days)
    result = run_screener_backtest(start, end, max_tickers=args.max_tickers)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
