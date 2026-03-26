from __future__ import annotations

def score(_symbol: str, opp: dict) -> float:
    return min(0.8, max(0.4, float(opp.get("score", 0.55)) + 0.05))
