from __future__ import annotations

def score(symbol: str, _opp: dict) -> float:
    return 0.64 if symbol in {"AAPL", "MSFT", "GOOGL"} else 0.56
