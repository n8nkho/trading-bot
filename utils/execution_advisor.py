from __future__ import annotations

from typing import Any


def advise_execution(*, confidence: float, volume_ratio: float, regime_label: str = "UNKNOWN") -> dict[str, Any]:
    conf = max(0.0, min(1.0, float(confidence)))
    vol = max(0.0, float(volume_ratio))
    regime = str(regime_label or "UNKNOWN").upper()
    urgency = "high" if conf >= 0.8 else ("medium" if conf >= 0.6 else "low")
    if regime in {"RISK_OFF", "HIGH_VOL"}:
        tactic = "passive_limit"
        slippage_bps = 8
    elif urgency == "high" and vol >= 1.5:
        tactic = "marketable_limit"
        slippage_bps = 15
    else:
        tactic = "passive_limit"
        slippage_bps = 10
    return {
        "tactic": tactic,
        "urgency": urgency,
        "max_slippage_bps": slippage_bps,
    }
