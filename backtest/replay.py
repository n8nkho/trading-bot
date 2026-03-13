#!/usr/bin/env python3
"""
Backtest & replay harness (read-only).

This script replays historical daily_signals files and computes simple
stop/target outcomes for screened candidates, without touching live
trading logic or data files.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.provider_safety import guarded_call


DATA_DIR = Path("data")


def _read_json(path: Path) -> Any:
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception:
        return None
    return None


def _iter_daily_signals(start: datetime | None, end: datetime | None):
    files = sorted(DATA_DIR.glob("daily_signals_*.json"))
    for p in files:
        stem = p.stem.replace("daily_signals_", "")
        if len(stem) != 8:
            continue
        try:
            d = datetime.strptime(stem, "%Y%m%d")
        except Exception:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        data = _read_json(p)
        if not isinstance(data, dict):
            continue
        data["_file_date"] = d
        yield data


def _check_outcome(ticker: str, signal_date: datetime, entry_price: float) -> Dict[str, Any] | None:
    try:
        import yfinance as yf

        def _do_history():
            start = signal_date.strftime("%Y-%m-%d")
            end = (signal_date + timedelta(days=10)).strftime("%Y-%m-%d")
            return yf.Ticker(ticker).history(start=start, end=end, interval="1d")

        hist = guarded_call("yfinance", _do_history)
        if hist is None or getattr(hist, "empty", True) or len(hist) < 2:
            return None
        hist = hist.sort_index()
        lows = hist["Low"]
        closes = hist["Close"]
        stop_pct = -4.0
        target_pct = 5.0
        for i in range(1, min(len(hist), 6)):
            low = float(lows.iloc[i])
            close = float(closes.iloc[i])
            pct_from_entry = (close - entry_price) / entry_price * 100.0
            drawdown = (low - entry_price) / entry_price * 100.0
            if drawdown <= stop_pct:
                return {"outcome": "stop_hit", "pct": pct_from_entry}
            if pct_from_entry >= target_pct:
                return {"outcome": "safe_win", "pct": pct_from_entry}
        last_close = float(closes.iloc[-1])
        pct = (last_close - entry_price) / entry_price * 100.0
        return {"outcome": "open", "pct": pct}
    except Exception:
        return None


def run_replay(days: int) -> Dict[str, Any]:
    end = datetime.now()
    start = end - timedelta(days=days)

    total = 0
    safe_wins = 0
    stops = 0
    sample: List[Dict[str, Any]] = []

    for s in _iter_daily_signals(start, end):
        signal_dt = s.get("_file_date") or end
        candidates = s.get("candidates", [])
        for c in candidates:
            if not isinstance(c, dict):
                continue
            ticker = c.get("ticker")
            entry = c.get("current_price") or 0
            if not ticker or entry <= 0:
                continue
            total += 1
            res = _check_outcome(str(ticker), signal_dt, float(entry))
            if not res:
                continue
            if res["outcome"] == "safe_win":
                safe_wins += 1
            if res["outcome"] == "stop_hit":
                stops += 1
            if len(sample) < 20:
                sample.append(
                    {
                        "ticker": ticker,
                        "signal_date": signal_dt.strftime("%Y-%m-%d"),
                        "outcome": res["outcome"],
                        "pct": res["pct"],
                    }
                )

    safe_rate = safe_wins / total if total else 0.0
    stop_rate = stops / total if total else 0.0
    return {
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "candidates_evaluated": total,
        "safe_wins": safe_wins,
        "stops": stops,
        "safe_win_rate": round(safe_rate, 3),
        "stop_rate": round(stop_rate, 3),
        "sample": sample,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay recent daily_signals for outcome stats (read-only).")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default: 30)")
    args = parser.parse_args()

    result = run_replay(args.days)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

