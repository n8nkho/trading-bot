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
    entries.append(
        {
            "ts_utc": summary["ts_utc"],
            "trade_count_total": len(trades),
            "snippet": f"last_window={len(recent)} trades (LLM summary optional; wire LLMRouter later)",
        }
    )
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
