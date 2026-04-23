"""
Fetch open positions from Alpaca (broker truth) for dashboard sync / drift detection.
"""
from __future__ import annotations

import os
from typing import Any

from utils.alpaca_env import is_alpaca_paper


def _alpaca_float(val: Any) -> float | None:
    """Parse Alpaca string/number fields; empty / None -> None (not 0)."""
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def normalize_alpaca_position(pos: Any) -> dict[str, Any]:
    """Map alpaca-py Position model to Command Center shape."""
    sym = str(getattr(pos, "symbol", "") or "")
    qty = _alpaca_float(getattr(pos, "qty", None)) or 0.0
    entry = _alpaca_float(getattr(pos, "avg_entry_price", None)) or 0.0
    cur = _alpaca_float(getattr(pos, "current_price", None))
    u_pnl = _alpaca_float(getattr(pos, "unrealized_pl", None))
    if u_pnl is None:
        u_pnl = 0.0
    basis = _alpaca_float(getattr(pos, "cost_basis", None)) or 0.0
    # Signed for long/short; dashboard uses abs for gross exposure when summing holdings value.
    mkt_val = _alpaca_float(getattr(pos, "market_value", None))
    # Alpaca API: unrealized_plpc is a ratio (0.20 = 20%); prefer over recomputing from basis.
    plpc_ratio = _alpaca_float(getattr(pos, "unrealized_plpc", None))
    if plpc_ratio is not None:
        pct = plpc_ratio * 100.0
    elif basis:
        pct = u_pnl / basis * 100.0
    else:
        pct = None
    return {
        "ticker": sym,
        "qty": qty,
        "entry_price": entry,
        "current_price": cur,
        "market_value": mkt_val,
        "pnl": round(u_pnl, 4),
        "pnl_pct": round(pct, 4) if pct is not None else None,
        "source": "alpaca_broker",
    }


def fetch_broker_positions() -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Returns (positions, error). positions is None only on failure (keys, import, API).
    Empty list means genuinely zero open positions at broker.
    """
    key = (os.getenv("ALPACA_API_KEY") or "").strip()
    sec = (os.getenv("ALPACA_SECRET_KEY") or "").strip()
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
