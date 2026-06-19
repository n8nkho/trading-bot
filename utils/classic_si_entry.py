"""Classic entry-gate SI — relax LLM/RSI caps when fill-recency objective gap persists."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import write_json_atomic
from utils.fill_recency_entry import (
    days_since_last_activity,
    days_since_last_fill,
    latest_regime,
    load_entry_overrides,
)

_ROOT = Path(__file__).resolve().parent.parent
_OVERRIDES_PATH = _ROOT / "data" / "entry_si_overrides.json"


def si_entry_enabled() -> bool:
    return str(os.environ.get("FORTRESS_CLASSIC_SI_ENTRY", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def maybe_auto_relax_entry_gate() -> dict[str, Any]:
    """Raise RSI / lower LLM confidence floor when fills are stale (bounded)."""
    if not si_entry_enabled():
        return {"skipped": "entry_si_disabled"}
    days = days_since_last_activity()
    if days is None:
        days = days_since_last_fill()
    if days is None:
        return {"skipped": "no_fill_history"}
    regime = latest_regime() or "unknown"
    ov = load_entry_overrides()
    step = int(ov.get("relax_step") or 0)
    if days < 7:
        return {"skipped": "recency_ok", "days_since_last_fill": days, "regime": regime}

    targets = [
        {"relaxed_rsi_cap": 66, "llm_min_confidence": 0.48, "position_size_mult": 0.75},
        {"relaxed_rsi_cap": 68, "llm_min_confidence": 0.45, "position_size_mult": 0.65},
        {"relaxed_rsi_cap": 70, "llm_min_confidence": 0.42, "position_size_mult": 0.55},
    ]
    target_step = min(len(targets) - 1, max(0, (days - 7) // 5))
    if days >= 21:
        target_step = len(targets) - 1
    if target_step <= step and ov.get("active"):
        if days != ov.get("days_since_last_fill"):
            refreshed = dict(ov)
            refreshed["days_since_last_fill"] = days
            refreshed["regime_at_apply"] = regime
            refreshed["updated_utc"] = datetime.now(timezone.utc).isoformat()
            _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(_OVERRIDES_PATH, refreshed)
            return {"ok": True, "mode": "entry_relax_refresh", **refreshed}
        return {
            "skipped": "no_relax_needed",
            "days_since_last_fill": days,
            "regime": regime,
            "relax_step": step,
        }
    patch = dict(targets[target_step])
    patch.update(
        {
            "active": True,
            "relax_step": target_step,
            "reason": "fill_recency_gap",
            "days_since_last_fill": days,
            "regime_at_apply": regime,
            "applied_by": "classic_si_entry",
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(_OVERRIDES_PATH, patch)
    return {"ok": True, **patch}
