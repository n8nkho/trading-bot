"""
Resolve customer / personal plan from environment or optional license file.

Lane 1 (you): FORTRESS_LICENSE_TIER=master
Lanes 2–3 (customers): tier from purchase + optional expiry in license.json
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Optional

VALID_TIERS = frozenset({"starter", "pro", "enterprise", "master"})

_TIER_DISPLAY = {
    "starter": "Starter",
    "pro": "Pro",
    "enterprise": "Enterprise",
    "master": "Master",
}


@dataclass(frozen=True)
class Plan:
    tier: str
    name: str
    valid: bool


def _parse_expires(raw: Any) -> Optional[datetime]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _load_license_file(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("license file must contain a JSON object")
    return data


def _invalid_plan(name: str = "Invalid license") -> Plan:
    return Plan(
        tier="starter",
        name=name,
        valid=False,
    )


def get_plan() -> Plan:
    """
    Resolution order:
    1. If FORTRESS_LICENSE_PATH is set, use that readable JSON file (tier, valid, expires).
       Missing/unreadable/malformed file data is invalid unless FORTRESS_LICENSE_TIER is
       explicitly set as a break-glass override.
    2. Else: FORTRESS_LICENSE_TIER env, else master (preserves existing installs).
    """
    path_str = os.environ.get("FORTRESS_LICENSE_PATH", "").strip()
    tier_from_env = os.environ.get("FORTRESS_LICENSE_TIER", "").strip().lower()

    data: dict[str, Any] = {}
    if path_str:
        p = Path(path_str).expanduser()
        if not p.is_file():
            if not tier_from_env:
                return _invalid_plan()
        else:
            try:
                data = _load_license_file(p)
            except (OSError, json.JSONDecodeError, ValueError):
                if not tier_from_env:
                    return _invalid_plan()
                data = {}

    if path_str:
        tier = str(data.get("tier") or tier_from_env).strip().lower()
        if not tier:
            return _invalid_plan()
    else:
        tier = (tier_from_env or "master").strip().lower()

    if tier not in VALID_TIERS:
        return _invalid_plan("Invalid tier")

    explicit_valid = data.get("valid") if data else None
    if explicit_valid is not None:
        valid = bool(explicit_valid)
    else:
        valid = True

    if data:
        exp = _parse_expires(data.get("expires_at") or data.get("expires"))
        if exp is not None and datetime.now(timezone.utc) > exp:
            valid = False

    name = str(data.get("name") or _TIER_DISPLAY.get(tier, tier.title()))

    return Plan(tier=tier, name=name, valid=valid)
