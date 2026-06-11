"""Runtime tunable parameters — parity with fortress-ai pre-trade position cap."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def override_path() -> Path:
    return _data_dir() / "tunable_params_overrides.json"


def load_overrides() -> dict[str, Any]:
    p = override_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_position_size_pct() -> float:
    """Fraction of portfolio/equity for max new BUY notional (clamped)."""
    try:
        cap = float(os.environ.get("FORTRESS_MAX_POSITION_SIZE_PCT", "0.03"))
    except ValueError:
        cap = 0.03
    try:
        base = float(os.environ.get("FORTRESS_POSITION_SIZE_PCT", str(cap)))
    except ValueError:
        base = cap
    base = max(0.02, min(cap, base))
    o = load_overrides().get("position_size_pct")
    if o is None:
        return base
    try:
        return max(0.02, min(cap, float(o)))
    except (TypeError, ValueError):
        return base
