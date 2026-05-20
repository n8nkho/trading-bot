"""
Fetch open positions from Alpaca (broker truth) for dashboard sync / drift detection.
"""
from __future__ import annotations

import os
from typing import Any

from utils.alpaca_env import is_alpaca_paper


def normalize_alpaca_position(pos: Any) -> dict[str, Any]:
    """Map alpaca-py Position model to Command Center shape."""
    sym = str(getattr(pos, "symbol", "") or "")
    try:
        qty = float(getattr(pos, "qty", 0) or 0)
    except (TypeError, ValueError):
        qty = 0.0
    try:
        entry = float(getattr(pos, "avg_entry_price", 0) or 0)
    except (TypeError, ValueError):
        entry = 0.0
    try:
        cur = float(getattr(pos, "current_price", 0) or 0)
    except (TypeError, ValueError):
        cur = 0.0
    try:
        u_pnl = float(getattr(pos, "unrealized_pl", 0) or 0)
    except (TypeError, ValueError):
        u_pnl = 0.0
    try:
        basis = float(getattr(pos, "cost_basis", 0) or 0)
    except (TypeError, ValueError):
        basis = 0.0
    pct = (u_pnl / basis * 100.0) if basis else None
    return {
        "ticker": sym,
        "qty": qty,
        "entry_price": entry,
        "current_price": cur,
        "pnl": round(u_pnl, 4),
        "pnl_pct": round(pct, 4) if pct is not None else None,
        "source": "alpaca_broker",
    }


def fetch_broker_positions() -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Returns (positions, error). positions is None only on failure (keys, import, API).
    Empty list means genuinely zero open positions at broker.
    """
    key = (os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID") or "").strip()
    sec = (os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY") or "").strip()
    if not key or not sec:
        return None, "missing_alpaca_keys"
    try:
        from alpaca.trading.client import TradingClient
    except ImportError:
        return None, "alpaca_sdk_missing"
    try:
        client = TradingClient(key, sec, paper=is_alpaca_paper())
        raw = client.get_all_positions()
    except Exception as e:
        return None, f"alpaca_error:{type(e).__name__}:{e}"
    out = [normalize_alpaca_position(p) for p in raw]
    out.sort(key=lambda x: str(x.get("ticker") or ""))
    return out, None
