import json
import os
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_POLICY_FILE = _ROOT / "config" / "policy_profiles.json"


def _load_policy_payload() -> dict:
    try:
        if _POLICY_FILE.exists():
            with open(_POLICY_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {"active_profile": "balanced", "profiles": {}}


def get_active_profile_name() -> str:
    try:
        from utils.policy_guardrails import get_effective_trading_profile_name

        return get_effective_trading_profile_name()
    except Exception:
        env_name = (os.getenv("TRADING_POLICY_PROFILE") or "").strip().lower()
        payload = _load_policy_payload()
        file_name = str(payload.get("active_profile") or "balanced").strip().lower()
        return env_name or file_name or "balanced"


def get_profile(name: str | None = None) -> dict:
    payload = _load_policy_payload()
    profiles = payload.get("profiles") or {}
    profile_name = (name or get_active_profile_name() or "balanced").strip().lower()
    profile = profiles.get(profile_name)
    if isinstance(profile, dict):
        return profile
    return profiles.get("balanced") or {}


def get_profile_bundle(name: str | None = None) -> dict:
    # When name is omitted, use effective profile (includes rollback / env).
    active = (name or get_active_profile_name() or "balanced").strip().lower()
    profile = get_profile(active)
    return {
        "active_profile": active,
        "description": profile.get("description"),
        "risk": profile.get("risk") or {},
        "screening": profile.get("screening") or {},
        "execution": profile.get("execution") or {},
    }
