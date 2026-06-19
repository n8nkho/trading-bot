"""Adaptive RSI ceiling — shared by screener prefilter and entry_agent."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json

_ROOT = Path(__file__).resolve().parent.parent
_CURRENT_PARAMS = _ROOT / "data" / "current_params.json"

# Hard ceiling for Classic oversold gate (matches classic_si_entry max relax step).
_MAX_CEILING = 70.0
_MIN_CEILING = 35.0


def _baseline_from_params() -> float:
    doc = read_json(_CURRENT_PARAMS, default={})
    if isinstance(doc, dict) and doc.get("rsi_threshold") is not None:
        try:
            return float(doc["rsi_threshold"])
        except (TypeError, ValueError):
            pass
    try:
        return float(os.environ.get("FORTRESS_CLASSIC_RSI_BASELINE", "40"))
    except ValueError:
        return 40.0


def adaptive_rsi_context() -> dict[str, Any]:
    """
    Unified adaptive RSI knobs for screener + entry.

    Strives upward when fill-recency SI is active; never below baseline params.
    """
    baseline = _baseline_from_params()
    ceiling = baseline
    sources: list[str] = ["current_params"]
    markers: list[str] = ["adaptive_rsi"]
    fill_recency_active = False

    try:
        from utils.fill_recency_entry import loosen_context

        fr = loosen_context() or {}
        if fr.get("active"):
            fill_recency_active = True
            cap = float(fr.get("relaxed_rsi_cap") or ceiling)
            if cap > ceiling:
                ceiling = cap
                sources.append("fill_recency_entry")
                markers.append("fill_recency_entry_loosen")
    except Exception:
        pass

    try:
        from utils.classic_si_entry import load_entry_overrides

        ov = load_entry_overrides()
        if ov.get("active") and ov.get("relaxed_rsi_cap") is not None:
            cap = float(ov["relaxed_rsi_cap"])
            if cap > ceiling:
                ceiling = cap
                if "entry_si_overrides" not in sources:
                    sources.append("entry_si_overrides")
                markers.append("classic_si_entry_relax")
    except Exception:
        pass

    ceiling = max(_MIN_CEILING, min(_MAX_CEILING, ceiling))
    return {
        "ceiling": ceiling,
        "baseline": baseline,
        "fill_recency_active": fill_recency_active,
        "sources": sources,
        "markers": markers,
    }


def adaptive_rsi_ceiling() -> float:
    return float(adaptive_rsi_context()["ceiling"])


def adaptive_ranging_oversold_cap() -> float:
    """Oversold ceiling for ranging-extremes prefilter (replaces fixed 35 when adaptive)."""
    ctx = adaptive_rsi_context()
    if ctx.get("fill_recency_active"):
        return float(ctx["ceiling"])
    # Default ranging oversold strict band unless params already relaxed.
    return max(35.0, min(float(ctx["ceiling"]), 55.0))


def adaptive_ranging_overbought_floor() -> float:
    """Overbought floor for ranging-extremes (symmetric slack when adaptive active)."""
    oversold = adaptive_ranging_oversold_cap()
    if oversold >= 60.0:
        return max(65.0, 100.0 - oversold)
    return 65.0


def tier_rsi_threshold(*, tier_rsi: float, tier_idx: int = 1) -> float:
    """Raise tier RSI threshold toward adaptive ceiling (never lower screener strictness)."""
    cap = adaptive_rsi_ceiling()
    tier_val = float(tier_rsi)
    if tier_idx <= 1 and cap > tier_val:
        return cap
    return min(cap, tier_val + max(0, (tier_idx - 1) * 4))
