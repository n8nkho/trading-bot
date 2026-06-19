"""Classic RecursiveScreener SI — bounded L2 min-score relax on post-recursive attrition."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json, write_json_atomic

_ROOT = Path(__file__).resolve().parent.parent
_OVERRIDES_PATH = _ROOT / "data" / "recursive_screener_si_overrides.json"
_HEALTH_PATH = _ROOT / "data" / "screening_pipeline_health.json"

_BASE_MIN_L2 = 65.0
_RELAX_STEPS: list[float] = [60.0, 55.0, 50.0]
_MAX_STEP = len(_RELAX_STEPS)


def si_recursive_enabled() -> bool:
    return str(os.environ.get("FORTRESS_CLASSIC_SI_RECURSIVE", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def load_overrides() -> dict[str, Any]:
    doc = read_json(_OVERRIDES_PATH, default={})
    return doc if isinstance(doc, dict) else {}


def save_overrides(doc: dict[str, Any]) -> None:
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(_OVERRIDES_PATH, doc)


def _base_min_layer2_score() -> float:
    raw = (os.environ.get("FORTRESS_RECURSIVE_SCREENER_MIN_L2") or "").strip()
    if raw:
        try:
            return max(45.0, min(75.0, float(raw)))
        except ValueError:
            pass
    return _BASE_MIN_L2


def attrition_context() -> dict[str, Any]:
    health = read_json(_HEALTH_PATH, default={})
    ov = load_overrides()
    raw = int((health or {}).get("daily_screen_last_raw_candidates") or 0)
    post = int((health or {}).get("daily_screen_last_candidates") or 0)
    streak = int((health or {}).get("daily_screen_consecutive_zero") or 0)
    return {
        "last_raw_candidates_found": raw,
        "last_candidates_found": post,
        "daily_screen_consecutive_zero": streak,
        "attrition_ratio": (post / raw) if raw > 0 else None,
        "relax_step": int(ov.get("relax_step") or 0),
        "overrides": ov,
    }


def effective_min_layer2_score() -> float:
    """Effective L2 floor for RecursiveScreener (never below 45)."""
    ov = load_overrides()
    step = int(ov.get("relax_step") or 0)
    if step > 0:
        return _RELAX_STEPS[min(step, _MAX_STEP) - 1]
    if ov.get("min_layer2_score") is not None:
        try:
            return max(45.0, min(75.0, float(ov["min_layer2_score"])))
        except (TypeError, ValueError):
            pass
    return _base_min_layer2_score()


def should_auto_relax(*, min_zero_streak: int = 2, min_raw: int = 3) -> tuple[bool, str]:
    if not si_recursive_enabled():
        return False, "recursive_si_disabled"
    ctx = attrition_context()
    step = int(ctx["relax_step"] or 0)
    if step >= _MAX_STEP:
        return False, "max_relax_step"
    raw = int(ctx["last_raw_candidates_found"] or 0)
    post = int(ctx["last_candidates_found"] or 0)
    streak = int(ctx["daily_screen_consecutive_zero"] or 0)
    if streak >= min_zero_streak:
        return True, "post_recursive_zero_streak"
    if raw >= min_raw and post == 0:
        return True, "high_attrition_run"
    return False, "attrition_ok"


def propose_relax_patch(*, force_step: int | None = None) -> dict[str, Any] | None:
    ok, reason = should_auto_relax()
    if not ok and force_step is None:
        return None
    ctx = attrition_context()
    cur = int(ctx["relax_step"] or 0)
    new_step = force_step if force_step is not None else cur + 1
    new_step = max(1, min(new_step, _MAX_STEP))
    if new_step <= cur and force_step is None:
        return None
    return {
        "relax_step": new_step,
        "min_layer2_score": _RELAX_STEPS[new_step - 1],
        "reason": reason if force_step is None else "forced",
        "last_raw_candidates_found": ctx["last_raw_candidates_found"],
        "last_candidates_found": ctx["last_candidates_found"],
        "daily_screen_consecutive_zero": ctx["daily_screen_consecutive_zero"],
    }


def apply_relax_patch(patch: dict[str, Any] | None = None) -> dict[str, Any]:
    patch = patch or propose_relax_patch()
    if not patch:
        return {"skipped": "no_patch", "context": attrition_context()}
    ov = load_overrides()
    ov.update(patch)
    ov["applied_by"] = "classic_si_recursive"
    save_overrides(ov)
    return {
        "ok": True,
        "applied": patch,
        "effective_min_layer2_score": effective_min_layer2_score(),
        "marker": "classic_si_recursive_relax",
    }


def reset_relax_on_candidates(*, candidates_found: int) -> None:
    if int(candidates_found) <= 0:
        return
    ov = load_overrides()
    if int(ov.get("relax_step") or 0) == 0:
        return
    ov["relax_step"] = 0
    ov.pop("min_layer2_score", None)
    ov["reset_reason"] = "post_recursive_candidates_found"
    ov["reset_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_overrides(ov)


def maybe_auto_relax_recursive() -> dict[str, Any]:
    if not si_recursive_enabled():
        return {"skipped": "recursive_si_disabled"}
    patch = propose_relax_patch()
    if not patch:
        return {"skipped": "no_relax_needed", "context": attrition_context()}
    return apply_relax_patch(patch)
