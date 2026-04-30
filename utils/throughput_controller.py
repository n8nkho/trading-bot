from __future__ import annotations

from typing import Any


def recommend_thresholds(
    *,
    current_params: dict[str, Any],
    candidates_found: int,
    target_min: int = 2,
    target_max: int = 5,
) -> dict[str, Any]:
    """
    Bounded step controller for screener throughput in existing parameter units.
    """
    out = dict(current_params or {})
    delta = 0
    if candidates_found < target_min:
        delta = 1
    elif candidates_found > target_max:
        delta = -1

    if delta == 0:
        return {"changed": False, "recommended_params": out, "reason": "within_band"}

    # Bounded one-step adjustments to avoid oscillation.
    out["rsi_threshold"] = float(out.get("rsi_threshold", 40)) + (1.0 * delta)
    out["volume_ratio_min"] = float(out.get("volume_ratio_min", 1.5)) - (0.05 * delta)
    out["drop_min"] = float(out.get("drop_min", -15)) - (1.0 * delta)
    out["drop_max"] = float(out.get("drop_max", -5)) + (0.5 * delta)

    # Safety clamps.
    out["rsi_threshold"] = max(35.0, min(55.0, out["rsi_threshold"]))
    out["volume_ratio_min"] = max(1.0, min(2.5, out["volume_ratio_min"]))
    out["drop_min"] = max(-50.0, min(-5.0, out["drop_min"]))
    out["drop_max"] = max(-10.0, min(5.0, out["drop_max"]))

    return {
        "changed": True,
        "recommended_params": out,
        "reason": "increase_throughput" if delta > 0 else "decrease_throughput",
    }
