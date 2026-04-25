#!/usr/bin/env python3
"""Pre-market briefing: macro/positions digest → logs + optional daily_risk_params."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.atomic_json import read_json, write_json_atomic
from utils.fortress_logger import FortressLogger

_DATA = _ROOT / "data"
_POSITIONS = _DATA / "positions.json"
_RISK_PARAMS = _DATA / "daily_risk_params.json"
_logger = FortressLogger("briefing")


def _allow_writes() -> bool:
    return os.environ.get("FORTRESS_BRIEFING_ALLOW_WRITES", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def run_briefing(*, dry_run: bool = True) -> dict:
    et = datetime.now(ZoneInfo("America/New_York"))
    dated = f"briefing_{et.strftime('%Y%m%d')}.log"
    positions = read_json(_POSITIONS, [])
    if isinstance(positions, dict):
        positions = positions.get("positions", [])
    if not isinstance(positions, list):
        positions = []
    tickers = [str(p.get("ticker", "")) for p in positions if isinstance(p, dict)]
    lines = [
        f"=== Briefing {et.isoformat()} ===",
        f"Open positions: {len(positions)} ({', '.join(tickers[:20])}{'…' if len(tickers) > 20 else ''})",
        "(Recursive Grok summarization can be wired via utils.llm_router.LLMRouter.)",
    ]
    text = "\n".join(lines)
    _logger.log_briefing(text, dated_filename=dated)

    summary = {
        "et": et.isoformat(),
        "position_count": len(positions),
        "dry_run": dry_run,
        "log": str(_ROOT / "logs" / dated),
    }

    if dry_run or not _allow_writes():
        return summary

    prev = read_json(
        _RISK_PARAMS,
        {"updated_at": "", "max_new_positions": None, "notes": ""},
    )
    if not isinstance(prev, dict):
        prev = {}
    prev["updated_at"] = et.isoformat()
    prev["notes"] = str(prev.get("notes") or "") + f" | briefing {et.date()}"
    write_json_atomic(_RISK_PARAMS, prev)
    return {**summary, "daily_risk_params_updated": True}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fortress pre-market briefing")
    ap.add_argument("--dry-run", action="store_true", help="No write to daily_risk_params.json")
    args = ap.parse_args()
    out = run_briefing(dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
