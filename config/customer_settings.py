"""
Bounded customer settings for risk appetite.

Customers can adjust a limited set of parameters within safe ranges to preserve capital.
Settings are read from data/customer_settings.json; invalid or out-of-range values
are clamped to bounds. Only used when license allows (customer_settings_allowed) and
file exists; otherwise core defaults apply.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from config.license import get_plan
from config.tiers import customer_settings_allowed

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CUSTOMER_SETTINGS_FILE = PROJECT_ROOT / "data" / "customer_settings.json"

# Bounds (min, max) for each key. Clamped on load.
BOUNDS = {
    "position_size_min": (200, 500),
    "position_size_max": (500, 2000),
    "stop_loss_pct": (-5.0, -1.0),  # e.g. -3% within -5% to -1%
    "take_profit_pct": (3.0, 15.0),
    "max_auto_trades_per_day": (2, 12),
    "min_confidence_for_auto": (0.65, 0.85),
    "daily_profit_target_dollars": (100, 500),
    "daily_profit_target_pct": (0.5, 2.0),
    "max_positions": (3, 10),
}

DEFAULTS = {
    "position_size_min": 300,
    "position_size_max": 750,
    "stop_loss_pct": -2.0,
    "take_profit_pct": 5.0,
    "max_auto_trades_per_day": 6,
    "min_confidence_for_auto": 0.70,
    "daily_profit_target_dollars": 250,
    "daily_profit_target_pct": 1.0,
    "max_positions": 5,
}


def _clamp(value: Any, key: str) -> Any:
    if key not in BOUNDS:
        return value
    try:
        lo, hi = BOUNDS[key]
        if isinstance(lo, int):
            return max(lo, min(hi, int(value)))
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return DEFAULTS.get(key, value)


def load_customer_settings() -> Dict[str, Any]:
    """
    Load and validate customer settings. Returns dict of clamped values;
    only keys in BOUNDS are returned. If tier does not allow or file missing,
    returns empty dict (callers use core defaults).
    """
    if not customer_settings_allowed(get_plan().tier):
        return {}
    if not CUSTOMER_SETTINGS_FILE.exists():
        return {}
    try:
        with open(CUSTOMER_SETTINGS_FILE) as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        out = {}
        for key in BOUNDS:
            if key in raw:
                out[key] = _clamp(raw[key], key)
            elif key in DEFAULTS:
                out[key] = DEFAULTS[key]
        return out
    except Exception:
        return {}


def get_customer_value(key: str, fallback: Any) -> Any:
    """Return customer setting for key if allowed and set; else fallback."""
    settings = load_customer_settings()
    return settings.get(key, fallback)
