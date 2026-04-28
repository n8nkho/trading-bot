#!/usr/bin/env python3
"""Nightly reflection over closed trades (trade_history.json → reflection_log.json)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.atomic_json import read_json, write_json_atomic
from utils.fortress_logger import FortressLogger

_DATA = _ROOT / "data"
_TRADE_HISTORY = _DATA / "trade_history.json"
_REFLECTION_LOG = _DATA / "reflection_log.json"
_logger = FortressLogger("reflection")


def _allow_writes() -> bool:
    return os.environ.get("FORTRESS_REFLECTION_ALLOW_WRITES", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _trade_pnl_pct(trade: dict) -> float | None:
    for key in ("pnl_pct", "pnl_percent", "return_pct", "realized_pnl_pct"):
        try:
            if key in trade and trade.get(key) is not None:
                return float(trade.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _build_reflection_entry(ts_utc: str, trades: list[dict], recent: list[dict]) -> dict:
    issues: list[str] = []
    wins = 0
    losses = 0
    scored = 0
    total_pnl = 0.0

    for t in recent:
        if not isinstance(t, dict):
            continue
        pnl = _trade_pnl_pct(t)
        if pnl is None:
            continue
        scored += 1
        total_pnl += pnl
        if pnl >= 0:
            wins += 1
        else:
            losses += 1

    score = 8.0
    if len(trades) == 0:
        score -= 4.0
        issues.append("No closed trades recorded in trade_history.json")
    if len(recent) == 0:
        score -= 1.0
        issues.append("No recent window available for reflection")
    if scored == 0 and len(recent) > 0:
        score -= 2.0
        issues.append("Recent trades missing pnl_pct/return_pct fields")
    if losses > wins and scored >= 3:
        score -= 2.0
        issues.append("Losses outnumber wins in reflection window")
    if total_pnl < -2.0 and scored >= 3:
        score -= 1.5
        issues.append("Net recent pnl_pct is materially negative")

    score = max(0.0, min(10.0, score))
    symbol = "portfolio"
    if recent and isinstance(recent[-1], dict):
        symbol = str(recent[-1].get("symbol") or symbol)

    if issues:
        feedback = "; ".join(issues)
    else:
        feedback = "Baseline checks healthy: trade history and pnl fields present"

    return {
        "ts_utc": ts_utc,
        "date": ts_utc[:10],
        "symbol": symbol,
        "score": round(score, 2),
        "feedback": feedback,
        "trade_count_total": len(trades),
        "trade_count_window": len(recent),
        "wins_window": wins,
        "losses_window": losses,
        "scored_trades_window": scored,
        "avg_pnl_pct_window": round(total_pnl / scored, 4) if scored > 0 else None,
    }


def run_reflection(*, dry_run: bool = True) -> dict:
    trades_doc = read_json(_TRADE_HISTORY, {"trades": []})
    trades = trades_doc.get("trades") if isinstance(trades_doc, dict) else []
    if not isinstance(trades, list):
        trades = []
    recent = trades[-50:] if len(trades) > 50 else trades
    summary = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "trade_count_total": len(trades),
        "trade_count_window": len(recent),
        "dry_run": dry_run,
    }
    _logger.log_reflection({"event": "reflection_run", **summary})

    if dry_run or not _allow_writes():
        return summary

    log_doc = read_json(_REFLECTION_LOG, {"entries": []})
    entries = log_doc.get("entries") if isinstance(log_doc, dict) else []
    if not isinstance(entries, list):
        entries = []
    entries.append(_build_reflection_entry(summary["ts_utc"], trades, recent))
    log_doc = {"entries": entries}
    write_json_atomic(_REFLECTION_LOG, log_doc)
    return {**summary, "reflection_appended": True}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fortress reflection agent")
    ap.add_argument("--dry-run", action="store_true", help="No writes to reflection_log.json")
    args = ap.parse_args()
    out = run_reflection(dry_run=args.dry_run)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
