"""
Policy guardrails: forced rollback profile, shadow candidate observation, drift hooks.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_POLICY_FILE = _ROOT / "config" / "policy_profiles.json"
_ROLLBACK_STATE = _ROOT / "data" / "policy_rollback_state.json"


def _load_policy_payload() -> dict:
    try:
        if _POLICY_FILE.exists():
            with open(_POLICY_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {"active_profile": "balanced", "profiles": {}, "guardrails": {}}


def get_guardrails() -> dict:
    payload = _load_policy_payload()
    g = payload.get("guardrails") or {}
    if not isinstance(g, dict):
        return {}
    return g


def _load_rollback_state() -> dict:
    try:
        if _ROLLBACK_STATE.exists():
            with open(_ROLLBACK_STATE, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_rollback_state(data: dict) -> None:
    _ROLLBACK_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(_ROLLBACK_STATE, "w") as f:
        json.dump(data, f, indent=2)


def clear_forced_rollback() -> dict:
    """Remove forced profile override (returns new state)."""
    state = _load_rollback_state()
    state.pop("forced_profile", None)
    state.pop("forced_at", None)
    state.pop("forced_reason", None)
    state.pop("forced_until", None)
    state["cleared_at"] = datetime.now().isoformat()
    _save_rollback_state(state)
    return state


def get_effective_trading_profile_name() -> str:
    """
    Resolution order:
    1) TRADING_POLICY_PROFILE env (operator override)
    2) Forced rollback profile in data/policy_rollback_state.json (if not expired)
    3) active_profile in policy_profiles.json
    """
    env_name = (os.getenv("TRADING_POLICY_PROFILE") or "").strip().lower()
    if env_name:
        return env_name

    state = _load_rollback_state()
    forced = (state.get("forced_profile") or "").strip().lower()
    until = state.get("forced_until")
    if forced:
        if until:
            try:
                exp = datetime.fromisoformat(str(until).replace("Z", "")[:26])
                if datetime.now() > exp:
                    forced = ""
            except Exception:
                pass
        if forced:
            return forced

    payload = _load_policy_payload()
    return str(payload.get("active_profile") or "balanced").strip().lower()


def _forced_rollback_still_active(existing: dict, *, target: str) -> bool:
    """True if drift rollback for `target` is already in force and not past forced_until."""
    forced = (existing.get("forced_profile") or "").strip().lower()
    reason = (existing.get("forced_reason") or "").strip().lower()
    if forced != (target or "").strip().lower() or reason != "drift_alert":
        return False
    until = existing.get("forced_until")
    if not until:
        return True
    try:
        s = str(until).replace("Z", "+00:00")
        exp = datetime.fromisoformat(s)
        exp_naive = exp.replace(tzinfo=None) if exp.tzinfo else exp
        return datetime.now() <= exp_naive
    except Exception:
        return True


def maybe_trigger_rollback_on_drift(drift_report: dict) -> dict | None:
    """
    If drift_alert and guardrails.auto_rollback_on_drift_alert, force safer profile.
    Returns action dict if rollback applied, else None.

    Idempotent: if the same drift rollback is already active, does not rewrite state
    or append trust events (avoids spam when /api/drift runs on every dashboard refresh).
    """
    guard = get_guardrails()
    if not guard.get("auto_rollback_on_drift_alert", True):
        return None
    if not drift_report.get("drift_alert"):
        return None

    if str(drift_report.get("reason") or "") == "no_recent_trading_activity":
        return None

    try:
        from utils.trading_activity import has_recent_trading_activity

        if not has_recent_trading_activity():
            return None
    except Exception:
        pass

    target = (guard.get("rollback_target_profile") or "capital_preservation").strip().lower()
    hours = int(guard.get("rollback_duration_hours") or 168)

    existing = _load_rollback_state()
    if _forced_rollback_still_active(existing, target=target):
        return None

    state = {
        "forced_profile": target,
        "forced_at": datetime.now().isoformat(),
        "forced_reason": "drift_alert",
        "forced_until": (datetime.now() + timedelta(hours=hours)).isoformat(),
        "drift_snapshot": {
            "recent_avg_pnl": drift_report.get("recent_avg_pnl"),
            "prior_avg_pnl": drift_report.get("prior_avg_pnl"),
            "drift_ratio": drift_report.get("drift_ratio"),
        },
    }
    _save_rollback_state(state)

    try:
        from utils.trust_ledger import append_trust_event

        append_trust_event("policy_rollback_triggered", {
            "forced_profile": target,
            "duration_hours": hours,
            "reason": "drift_alert",
        })
    except Exception:
        pass

    return {"action": "rollback_applied", "forced_profile": target, "until": state["forced_until"]}


def get_public_rollback_status() -> dict:
    s = _load_rollback_state()
    return {
        "forced_profile": s.get("forced_profile"),
        "forced_at": s.get("forced_at"),
        "forced_until": s.get("forced_until"),
        "forced_reason": s.get("forced_reason"),
    }


def shadow_policy_snapshot() -> dict | None:
    """If shadow mode enabled with a candidate profile, return comparison payload for ledger."""
    guard = get_guardrails()
    if not guard.get("shadow_mode_enabled"):
        return None
    candidate = (guard.get("shadow_candidate_profile") or "").strip().lower()
    if not candidate:
        return None

    try:
        from utils.policy_profile import get_profile_bundle

        live_name = get_effective_trading_profile_name()
        live = get_profile_bundle(live_name)
        cand = get_profile_bundle(candidate)
        return {
            "live_profile": live_name,
            "shadow_candidate_profile": candidate,
            "live_risk": live.get("risk") or {},
            "shadow_risk": cand.get("risk") or {},
            "live_screening": live.get("screening") or {},
            "shadow_screening": cand.get("screening") or {},
            "note": "Shadow candidate is observe-only; live execution uses effective profile.",
        }
    except Exception:
        return None
