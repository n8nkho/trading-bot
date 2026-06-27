"""
Classic screener SI — adaptive bear/ranging throughput when zero-candidate streaks.

Writes bounded overrides to data/screener_si_overrides.json (never weakens pre_trade_gate).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json, write_json_atomic

_ROOT = Path(__file__).resolve().parent.parent
_OVERRIDES_PATH = _ROOT / "data" / "screener_si_overrides.json"
_HEALTH_PATH = _ROOT / "data" / "screening_pipeline_health.json"
_META_PATH = _ROOT / "data" / "last_screening_meta.json"
_RISK_PATH = _ROOT / "data" / "daily_risk_params.json"

# Default non-bull tier-1 baseline (matches screener_agent defaults)
_BEAR_BASE = {
    "bear_rsi_t1": 40,
    "bear_drop_min": -15,
    "bear_drop_max": -5,
    "bear_volume_ratio_min": 1.5,
    "bear_ranging_extremes": False,
}

# Progressive relaxation steps (bounded)
_RELAX_STEPS: list[dict[str, Any]] = [
    {
        "bear_rsi_t1": 48,
        "bear_drop_min": -8,
        "bear_drop_max": 3,
        "bear_volume_ratio_min": 1.15,
        "bear_ranging_extremes": False,
    },
    {
        "bear_rsi_t1": 55,
        "bear_drop_min": -3,
        "bear_drop_max": 6,
        "bear_volume_ratio_min": 0.95,
        "bear_ranging_extremes": True,
    },
    {
        "bear_rsi_t1": 62,
        "bear_drop_min": -1,
        "bear_drop_max": 8,
        "bear_volume_ratio_min": 0.80,
        "bear_ranging_extremes": True,
    },
]

_MAX_STEP = len(_RELAX_STEPS)


def si_screener_enabled() -> bool:
    return str(os.environ.get("FORTRESS_CLASSIC_SI_SCREENER", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def overrides_path() -> Path:
    return _OVERRIDES_PATH


def load_overrides() -> dict[str, Any]:
    doc = read_json(_OVERRIDES_PATH, default={})
    return doc if isinstance(doc, dict) else {}


def save_overrides(doc: dict[str, Any]) -> None:
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(_OVERRIDES_PATH, doc)


def _current_regime() -> str:
    doc = read_json(_RISK_PATH, default={})
    if isinstance(doc, dict):
        return str(doc.get("regime") or "").strip().upper() or "RANGING"
    meta = read_json(_META_PATH, default={})
    if isinstance(meta, dict):
        return str(meta.get("market_regime_at_screen") or "").strip().upper() or "RANGING"
    return "RANGING"


def screening_context() -> dict[str, Any]:
    health = read_json(_HEALTH_PATH, default={})
    meta = read_json(_META_PATH, default={})
    ov = load_overrides()
    daily_zero = int((health or {}).get("daily_screen_consecutive_zero") or 0)
    daily_last = (health or {}).get("daily_screen_last_candidates")
    if daily_zero or daily_last is not None:
        consecutive = daily_zero
        last_cands = int(daily_last if daily_last is not None else 0)
    else:
        consecutive = int((health or {}).get("consecutive_zero_runs") or 0)
        last_cands = int((health or {}).get("last_candidates_found") or (meta or {}).get("candidates_found") or 0)
    regime = _current_regime()
    filter_counts = (meta or {}).get("filter_counts") if isinstance(meta, dict) else {}
    return {
        "regime": regime,
        "consecutive_zero_runs": consecutive,
        "last_candidates_found": last_cands,
        "daily_screen_consecutive_zero": daily_zero,
        "relax_step": int(ov.get("relax_step") or 0),
        "filter_counts": filter_counts or {},
        "overrides": ov,
    }


def effective_bear_tier1() -> dict[str, Any]:
    """Merged tier-1 params for non-bull regimes."""
    ov = load_overrides()
    out = dict(_BEAR_BASE)
    step = int(ov.get("relax_step") or 0)
    if step > 0:
        merged = _RELAX_STEPS[min(step, _MAX_STEP) - 1]
        out.update({k: merged[k] for k in _BEAR_BASE if k in merged})
        for k in _BEAR_BASE:
            if k in ov and ov[k] is not None:
                out[k] = ov[k]
    env_rsi = os.environ.get("FORTRESS_SCREENER_BEAR_RSI_T1")
    if env_rsi:
        try:
            out["bear_rsi_t1"] = int(float(env_rsi))
        except ValueError:
            pass
    try:
        from utils.adaptive_rsi import adaptive_rsi_ceiling

        cap = int(adaptive_rsi_ceiling())
        if cap > int(out.get("bear_rsi_t1") or 0):
            out["bear_rsi_t1"] = cap
    except Exception:
        pass
    return out


def should_auto_relax(*, min_zero_runs: int = 2) -> tuple[bool, str]:
    if not si_screener_enabled():
        return False, "screener_si_disabled"
    ctx = screening_context()
    regime = str(ctx["regime"] or "").upper()
    if regime in ("TRENDING_BULL", "BULL") and int(ctx.get("daily_screen_consecutive_zero") or 0) < 2:
        return False, "bull_regime_use_bull_tiers"
    daily_zero = int(ctx.get("daily_screen_consecutive_zero") or 0)
    if daily_zero >= 2:
        pass
    else:
        effective_min = 1 if regime in ("VOLATILE", "TRENDING_BEAR", "BEAR", "RANGING") else min_zero_runs
        if ctx["consecutive_zero_runs"] < effective_min and ctx["last_candidates_found"] > 0:
            return False, "candidates_ok"
    step = int(ctx["relax_step"] or 0)
    if step >= _MAX_STEP:
        return False, "max_relax_step"
    return True, "zero_candidate_streak"


def propose_relax_patch(*, force_step: int | None = None) -> dict[str, Any] | None:
    ok, reason = should_auto_relax()
    if not ok and force_step is None:
        return None
    ctx = screening_context()
    cur_step = int(ctx["relax_step"] or 0)
    new_step = force_step if force_step is not None else cur_step + 1
    new_step = max(1, min(new_step, _MAX_STEP))
    if new_step <= cur_step and force_step is None:
        return None
    patch = dict(_RELAX_STEPS[new_step - 1])
    patch["relax_step"] = new_step
    patch["regime_at_apply"] = ctx["regime"]
    patch["reason"] = reason if force_step is None else "forced"
    patch["consecutive_zero_runs"] = ctx["consecutive_zero_runs"]
    return patch


def apply_relax_patch(patch: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply next screener relaxation step."""
    patch = patch or propose_relax_patch()
    if not patch:
        return {"skipped": "no_patch", "context": screening_context()}

    ov = load_overrides()
    ov.update(patch)
    ov["applied_by"] = "classic_si_screener"
    save_overrides(ov)
    result = {
        "ok": True,
        "applied": patch,
        "effective_tier1": effective_bear_tier1(),
        "marker": "classic_si_screener_relax",
    }
    try:
        from utils.si_rsi_auto_deploy import deploy_screener_relax

        result["rsi_deploy"] = deploy_screener_relax(reason=str(patch.get("reason") or "relax"))
    except Exception:
        pass
    return result


def reset_relax_on_candidates(*, candidates_found: int) -> None:
    """Reset relax step and stale bear overrides when screening produces candidates."""
    if int(candidates_found) <= 0:
        return
    ov = load_overrides()
    step = int(ov.get("relax_step") or 0)
    stale_bear = any(
        ov.get(k) is not None and ov.get(k) != _BEAR_BASE.get(k) for k in _BEAR_BASE
    )
    if step == 0 and not stale_bear:
        return
    save_overrides(
        {
            "relax_step": 0,
            "reset_reason": "candidates_found",
            "reset_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


def maybe_auto_relax_screener() -> dict[str, Any]:
    """Entry point for evolve / autonomous SI."""
    if not si_screener_enabled():
        return {"skipped": "screener_si_disabled"}
    patch = propose_relax_patch()
    if not patch:
        return {"skipped": "no_relax_needed", "context": screening_context()}
    return apply_relax_patch(patch)
