from __future__ import annotations

from typing import Any


def _clamp_0_100(v: float) -> float:
    return max(0.0, min(100.0, float(v)))


def score_candidate(candidate: dict[str, Any], regime_label: str = "UNKNOWN") -> dict[str, Any]:
    """
    Deterministic convergence scoring used in uplift shadow mode.
    Returns full factor decomposition for dashboard/operator explainability.
    """
    drop_pct = float(candidate.get("drop_pct") or 0.0)
    rsi = float(candidate.get("rsi") or 50.0)
    volume_ratio = float(candidate.get("volume_ratio") or 1.0)
    llm_conf = float((candidate.get("analysis") or {}).get("confidence") or 0.5)
    vision = candidate.get("vision_signal") or {}
    vision_sig = str(vision.get("signal") or "").upper()

    # Momentum quality: favor oversold but not crash-like RSI.
    momentum = _clamp_0_100((55.0 - rsi) * 2.0)
    # Reversion geometry: sweet spot around moderate down move.
    rev_dist = abs(drop_pct + 9.0)
    reversion = _clamp_0_100(100.0 - (rev_dist * 7.0))
    # Participation confirmation.
    volume = _clamp_0_100((volume_ratio - 0.8) * 60.0)
    # News/analysis confidence from existing stack.
    narrative = _clamp_0_100(llm_conf * 100.0)
    # Vision alignment as a coarse prior.
    if vision_sig in {"STRONG_BUY", "BUY"}:
        pattern = 85.0
    elif vision_sig == "HOLD":
        pattern = 55.0
    elif vision_sig == "AVOID":
        pattern = 20.0
    else:
        pattern = 50.0
    # Regime penalty/bonus. Keep simple to avoid instability.
    regime = str(regime_label or "UNKNOWN").upper()
    regime_adj = 5.0 if regime in {"RISK_ON", "TRENDING"} else (-8.0 if regime in {"RISK_OFF", "HIGH_VOL"} else 0.0)

    weights = {
        "momentum_quality": 0.25,
        "reversion_geometry": 0.20,
        "volume_confirmation": 0.20,
        "narrative_confidence": 0.20,
        "pattern_alignment": 0.15,
    }
    base = (
        momentum * weights["momentum_quality"]
        + reversion * weights["reversion_geometry"]
        + volume * weights["volume_confirmation"]
        + narrative * weights["narrative_confidence"]
        + pattern * weights["pattern_alignment"]
    )
    score = _clamp_0_100(base + regime_adj)

    return {
        "convergence_score": round(score, 2),
        "confidence": round(score / 100.0, 4),
        "regime_label": regime,
        "factor_breakdown": {
            "momentum_quality": round(momentum, 2),
            "reversion_geometry": round(reversion, 2),
            "volume_confirmation": round(volume, 2),
            "narrative_confidence": round(narrative, 2),
            "pattern_alignment": round(pattern, 2),
            "regime_adjustment": round(regime_adj, 2),
            "weights": weights,
        },
    }
