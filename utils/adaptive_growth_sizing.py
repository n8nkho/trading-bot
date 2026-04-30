from __future__ import annotations

from typing import Any

from utils.uplift_runtime import get_limits


def recommend_size(
    *,
    equity_usd: float,
    current_price: float,
    confidence: float,
    deployed_usd: float,
    overnight_exposure_usd: float,
    overnight_candidate: bool,
) -> dict[str, Any]:
    """
    Shadow-safe adaptive growth sizing with hard envelope constraints.
    """
    lim = get_limits()
    max_total = float(lim["max_total_deployed_usd"])
    max_pos = max(0.0, float(equity_usd) * float(lim["max_position_equity_ratio"]))
    max_overnight = max_total * float(lim["max_overnight_exposure_ratio"])

    conf = max(0.0, min(1.0, float(confidence)))
    raw_target = max_pos * (0.65 + 0.7 * conf)  # 65%..135% of base position cap
    available_total = max(0.0, max_total - float(deployed_usd))
    capped = min(raw_target, max_pos, available_total)

    overnight_blocked = False
    if overnight_candidate and (overnight_exposure_usd + capped > max_overnight):
        overnight_blocked = True
        capped = max(0.0, max_overnight - overnight_exposure_usd)

    shares = int(capped / max(float(current_price), 0.0001))
    applied = shares * float(current_price) if shares > 0 else 0.0
    return {
        "recommended_position_usd": round(applied, 2),
        "recommended_shares": int(shares),
        "max_total_deployed_usd": max_total,
        "max_position_usd": round(max_pos, 2),
        "max_overnight_exposure_usd": round(max_overnight, 2),
        "overnight_blocked": overnight_blocked,
        "shadow_reason": "adaptive_growth_sizing",
    }
