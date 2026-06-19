"""Track consecutive zero-candidate screening runs for operator alerts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json, write_json_atomic

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "screening_pipeline_health.json"


def record_screening_outcome(*, candidates_found: int) -> dict[str, Any]:
    """Periodic screener_agent runs (intraday refresh)."""
    doc = read_json(_PATH, default={})
    if not isinstance(doc, dict):
        doc = {}
    prev = int(doc.get("consecutive_zero_runs") or 0)
    if int(candidates_found) <= 0:
        consecutive = prev + 1
    else:
        consecutive = 0
    out = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_candidates_found": int(candidates_found),
        "consecutive_zero_runs": consecutive,
    }
    if consecutive >= 3:
        out["operator_warn"] = (
            "3+ consecutive screening runs with 0 candidates — review prefilter thresholds and watchlist."
        )
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(_PATH, {**doc, **out})
    return out


def record_daily_screen_outcome(
    *,
    candidates_found: int,
    raw_candidates_found: int | None = None,
) -> dict[str, Any]:
    """Daily orchestrator screen (post-RecursiveScreener) — drives classic SI relax."""
    doc = read_json(_PATH, default={})
    if not isinstance(doc, dict):
        doc = {}
    prev = int(doc.get("daily_screen_consecutive_zero") or 0)
    cands = int(candidates_found)
    consecutive = prev + 1 if cands <= 0 else 0
    out: dict[str, Any] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "daily_screen_last_candidates": cands,
        "daily_screen_consecutive_zero": consecutive,
        "daily_screen_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if raw_candidates_found is not None:
        out["daily_screen_last_raw_candidates"] = int(raw_candidates_found)
        raw_n = int(raw_candidates_found)
        if raw_n > 0 and cands == 0:
            out["daily_screen_attrition_warn"] = (
                f"RecursiveScreener rejected all {raw_n} raw candidates — review L2 min score."
            )
    if consecutive >= 2:
        out["daily_screen_operator_warn"] = (
            f"{consecutive} consecutive daily screens with 0 post-recursive candidates."
        )
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(_PATH, {**doc, **out})
    return out
