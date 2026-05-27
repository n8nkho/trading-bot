"""Regime snapshot freshness helpers for entry gates and scorecards."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json
from utils.market_calendar import is_us_equity_rth_open

_ROOT = Path(__file__).resolve().parent.parent
_RISK_PATH = _ROOT / "data" / "daily_risk_params.json"


def load_regime_snapshot() -> dict[str, Any]:
    doc = read_json(_RISK_PATH, default={})
    return doc if isinstance(doc, dict) else {}


def regime_age_minutes() -> float | None:
    raw = load_regime_snapshot().get("regime_detected_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return None


def refresh_regime_if_stale_rth(*, max_age_minutes: float | None = None) -> dict[str, Any] | None:
    """
    Self-heal: refresh regime snapshot during RTH when stale (rate-limited).
    Returns detector output dict or None if skipped/fresh.
    """
    import os
    import time

    if str(os.getenv("FORTRESS_REGIME_AUTO_REFRESH_RTH", "1")).strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return None
    stale, _why = regime_is_stale_for_rth(max_age_minutes=max_age_minutes)
    if not stale:
        return None

    lock = _ROOT / "data" / ".regime_auto_refresh.ts"
    try:
        min_gap = float(os.getenv("FORTRESS_REGIME_AUTO_REFRESH_MIN_SEC", "120"))
    except ValueError:
        min_gap = 120.0
    now_ts = time.time()
    if lock.exists():
        try:
            last = float(lock.read_text(encoding="utf-8").strip())
            if now_ts - last < min_gap:
                return {"skipped": "rate_limited", "min_gap_sec": min_gap}
        except Exception:
            pass

    try:
        from agents.regime_detector import RegimeDetector

        out = RegimeDetector().detect_regime(dry_run=False)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(now_ts), encoding="utf-8")
        return out if isinstance(out, dict) else {"ok": True}
    except Exception as exc:
        return {"error": str(exc)[:200]}


def regime_is_stale_for_rth(*, max_age_minutes: float | None = None) -> tuple[bool, str]:
    """
    During US equity RTH, stale if older than max_age_minutes (default env or 60).
    Outside RTH, never stale (returns False) unless FORCE_STALE check is needed by caller.
    """
    if not is_us_equity_rth_open():
        return False, "outside_rth"
    mx = max_age_minutes
    if mx is None:
        try:
            mx = float(os.getenv("FORTRESS_REGIME_MAX_AGE_MINUTES_RTH", "60"))
        except ValueError:
            mx = 60.0
    age = regime_age_minutes()
    if age is None:
        return True, "missing_regime_timestamp"
    snap = load_regime_snapshot()
    if snap.get("regime_stale"):
        return True, "flagged_stale"
    if age > mx:
        return True, f"age_minutes={age:.1f}>{mx:.1f}"
    return False, "fresh"


def sentiment_pipeline_meta() -> dict[str, Any]:
    """Load sentiment_velocity.json metadata + staleness during RTH."""
    p = _ROOT / "data" / "sentiment_velocity.json"
    doc = read_json(p, default={})
    if not isinstance(doc, dict):
        doc = {}
    meta = doc.get("pipeline_meta") if isinstance(doc.get("pipeline_meta"), dict) else {}
    last = meta.get("last_full_run_at") or meta.get("last_updated_display") or doc.get("generated_at")
    age_min = None
    if last:
        try:
            dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
        except Exception:
            age_min = None
    stale = False
    if is_us_equity_rth_open() and age_min is not None:
        try:
            lim = float(os.getenv("FORTRESS_SENTIMENT_MAX_AGE_MINUTES_RTH", "45"))
        except ValueError:
            lim = 45.0
        stale = age_min > lim
    return {
        "last_updated": last,
        "age_minutes": age_min,
        "stale_during_rth": stale,
        "confidence_multiplier": 0.5 if stale else 1.0,
    }
