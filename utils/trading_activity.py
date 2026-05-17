"""Recent realized-fill activity from pnl_ledger.jsonl (for drift / rollback gating)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LEDGER = _ROOT / "data" / "pnl_ledger.jsonl"


def _parse_row_ts(row: dict) -> datetime | None:
    for key in ("timestamp", "closed_at", "filled_at", "exit_time", "ts"):
        raw = row.get(key)
        if not raw:
            continue
        try:
            s = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None


def last_realized_fill_at(*, ledger_path: Path | None = None) -> datetime | None:
    path = ledger_path or _LEDGER
    if not path.exists():
        return None
    latest: datetime | None = None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                dt = _parse_row_ts(row)
                if dt and (latest is None or dt > latest):
                    latest = dt
    except Exception:
        return None
    return latest


def has_recent_trading_activity(days: float | None = None, *, ledger_path: Path | None = None) -> bool:
    """
    True if at least one realized fill exists within the lookback window.
    Default window: FORTRESS_DRIFT_MIN_ACTIVITY_DAYS (10).
    """
    if days is None:
        try:
            days = float(os.getenv("FORTRESS_DRIFT_MIN_ACTIVITY_DAYS", "10"))
        except Exception:
            days = 10.0
    last = last_realized_fill_at(ledger_path=ledger_path)
    if last is None:
        return False
    now = datetime.now(timezone.utc)
    age_days = (now - last).total_seconds() / 86400.0
    return age_days <= float(days)
