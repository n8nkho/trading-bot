from __future__ import annotations

from typing import Any


def build_execution_plan(trade: dict[str, Any], *, market_open: bool = True) -> dict[str, Any]:
    """
    Simple execution planner:
    - Options default to LIMIT when an entry price is present.
    - Stocks default to MARKET during RTH, otherwise LIMIT at reference entry.
    """
    trade_type = str(trade.get("trade_type") or trade.get("type") or "STOCK").upper()
    entry = trade.get("entry_price")
    if trade_type == "OPTION":
        if entry is not None:
            return {"order_type": "limit", "limit_price": round(float(entry), 2), "time_in_force": "day"}
        return {"order_type": "market", "limit_price": None, "time_in_force": "day"}
    if market_open:
        return {"order_type": "market", "limit_price": None, "time_in_force": "day"}
    if entry is not None:
        return {"order_type": "limit", "limit_price": round(float(entry), 2), "time_in_force": "day"}
    return {"order_type": "market", "limit_price": None, "time_in_force": "day"}

