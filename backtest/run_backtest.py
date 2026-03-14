#!/usr/bin/env python3
"""
Single entry point for all backtests.
  python backtest/run_backtest.py replay --days 30
  python backtest/run_backtest.py screener --days 30
  python backtest/run_backtest.py screener --start 2025-01-01 --end 2025-03-01
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fortress backtest: replay or screener.")
    parser.add_argument("strategy", choices=["replay", "screener"], help="replay = daily_signals replay; screener = historical screener backtest")
    parser.add_argument("--days", type=int, default=30, help="Lookback days (replay or screener)")
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD (screener)")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (screener)")
    parser.add_argument("--max-tickers", type=int, default=50, help="Max tickers (screener)")
    args = parser.parse_args()

    # License tier gate
    try:
        from config.license import get_plan
        from config.tiers import backtest_allowed
        if not backtest_allowed(get_plan().tier):
            print("Backtest is not included in your license tier. Upgrade to Pro or Enterprise.", file=sys.stderr)
            return 1
    except Exception:
        pass

    if args.strategy == "replay":
        from backtest.replay import run_replay
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=args.days)
        result = run_replay(args.days)
        print(json.dumps(result, indent=2))
        return 0

    if args.strategy == "screener":
        from backtest.strategy_backtest import run_screener_backtest
        from datetime import datetime, timedelta
        end = datetime.now()
        if args.end:
            try:
                end = datetime.strptime(args.end, "%Y-%m-%d")
            except ValueError:
                print("Invalid --end; use YYYY-MM-DD", file=sys.stderr)
                return 1
        if args.start:
            try:
                start = datetime.strptime(args.start, "%Y-%m-%d")
            except ValueError:
                print("Invalid --start; use YYYY-MM-DD", file=sys.stderr)
                return 1
        else:
            start = end - timedelta(days=args.days)
        result = run_screener_backtest(start, end, max_tickers=args.max_tickers)
        print(json.dumps(result, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
