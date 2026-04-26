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
    # ── Sentiment velocity hook (read-only) ──────────────────────────────
    try:
        if os.path.exists("data/sentiment_velocity.json"):
            from utils.atomic_json import read_json as _read_json

            _sv = _read_json("data/sentiment_velocity.json", default={})
            _sv_symbols = _sv.get("symbols", {})
            if _sv_symbols:
                _logger.log_briefing("\nSENTIMENT VELOCITY:", dated_filename=dated)
                for _sym, _sv_data in _sv_symbols.items():
                    _cls = _sv_data.get("classification", "UNKNOWN")
                    _vel = _sv_data.get("velocity", 0)
                    _sig = _sv_data.get("signal", "")
                    _theme = _sv_data.get("key_themes", [])
                    _theme_str = ", ".join(_theme[:2]) if _theme else ""
                    _logger.log_briefing(
                        f"  {_sym} — {_cls} (velocity: {_vel:+.2f}) "
                        f"| signal: {_sig}"
                        + (f" | {_theme_str}" if _theme_str else ""),
                        dated_filename=dated,
                    )
            else:
                _logger.log_briefing("\nSENTIMENT VELOCITY: no data yet", dated_filename=dated)
    except Exception as _e:
        _logger.log_briefing(f"\nSENTIMENT VELOCITY: unavailable ({_e})", dated_filename=dated)
    # ── End sentiment velocity hook ───────────────────────────────────────
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
