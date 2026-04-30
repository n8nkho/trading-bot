from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_UPLIFT_STATUS_PATH = _ROOT / "uplift_status.json"


def _default_status() -> dict[str, Any]:
    return {
        "version": "2.0",
        "current_phase": "PLANNING",
        "feature_flags": {
            "FORTRESS_UPLIFT_CONVERGENCE_MODE": 0,
            "FORTRESS_UPLIFT_ADAPTIVE_SIZING_MODE": 0,
            "FORTRESS_UPLIFT_THROUGHPUT_MODE": 0,
            "FORTRESS_UPLIFT_EXECUTION_ADVISOR_MODE": 0,
        },
        "limits": {
            "max_total_deployed_usd": 25000.0,
            "max_overnight_exposure_ratio": 0.30,
            "max_position_equity_ratio": 0.10,
        },
    }


def load_uplift_status() -> dict[str, Any]:
    if not _UPLIFT_STATUS_PATH.exists():
        return _default_status()
    try:
        doc = json.loads(_UPLIFT_STATUS_PATH.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            return doc
    except Exception:
        pass
    return _default_status()


def get_flag_mode(flag_name: str) -> int:
    status = load_uplift_status()
    flags = status.get("feature_flags") if isinstance(status.get("feature_flags"), dict) else {}
    raw = flags.get(flag_name, 0)
    try:
        mode = int(raw)
    except Exception:
        mode = 0
    if mode < 0:
        return 0
    if mode > 2:
        return 2
    return mode


def get_limits() -> dict[str, float]:
    status = load_uplift_status()
    limits = status.get("limits") if isinstance(status.get("limits"), dict) else {}
    out: dict[str, float] = {}
    for k, dv in {
        "max_total_deployed_usd": 25000.0,
        "max_overnight_exposure_ratio": 0.30,
        "max_position_equity_ratio": 0.10,
    }.items():
        try:
            out[k] = float(limits.get(k, dv))
        except Exception:
            out[k] = dv
    return out
