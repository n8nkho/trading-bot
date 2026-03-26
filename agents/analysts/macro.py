from __future__ import annotations

def score(_symbol: str, opp: dict) -> float:
    theme = str(opp.get("theme", ""))
    return 0.67 if "macro" in theme or "volatility" in theme else 0.58
