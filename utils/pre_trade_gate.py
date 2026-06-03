"""
Central pre-submit gate for broker orders — compliance-style hard blocks.
All paths that submit orders should call evaluate_pre_trade_submission() first.
"""

from __future__ import annotations

import os
from typing import Any

from utils.operator_halt import is_trading_halted


def evaluate_pre_trade_submission(
    *,
    side: str,
    symbol: str,
    qty: float,
    estimated_notional_usd: float | None = None,
    order_class: str = "equity",
) -> dict[str, Any]:
    """
    Returns {"allowed": bool, "reasons": [str, ...]}.
    """
    reasons: list[str] = []

    if is_trading_halted():
        reasons.append("global_trading_halt")

    base = (os.getenv("ALPACA_BASE_URL") or "").lower()
    live_ack = (os.getenv("FORTRESS_LIVE_TRADING_ACK") or "").strip()
    if base and "paper" not in base and live_ack != "I_ACCEPT_LIVE_RISK":
        reasons.append("non_paper_endpoint_without_live_ack")

    try:
        max_notional = float(os.environ.get("FORTRESS_MAX_ORDER_NOTIONAL_USD", "25000"))
    except ValueError:
        max_notional = 25000.0
    normalized_order_class = (order_class or "").strip().lower()
    if (
        normalized_order_class == "option"
        and (side or "").strip().upper() == "BUY"
        and estimated_notional_usd is None
    ):
        reasons.append("missing_option_notional_estimate")
    if estimated_notional_usd is not None and estimated_notional_usd > max_notional:
        reasons.append(f"estimated_notional_exceeds_cap:{max_notional}")

    try:
        max_qty = float(os.environ.get("FORTRESS_MAX_ORDER_QTY", "5000"))
    except ValueError:
        max_qty = 5000.0
    if qty and abs(float(qty)) > max_qty:
        reasons.append(f"qty_exceeds_cap:{max_qty}")

    sym = (symbol or "").strip().upper()
    if not sym:
        reasons.append("missing_symbol")

    sd = (side or "").strip().upper()
    if sd not in ("BUY", "SELL"):
        reasons.append("invalid_side")

    return {
        "allowed": len(reasons) == 0,
        "reasons": reasons,
        "order_class": order_class,
        "symbol": sym,
        "side": sd,
        "qty": qty,
    }


def format_gate_block_message(gate: dict[str, Any]) -> str:
    return "pre_trade_gate: " + ",".join(gate.get("reasons") or [])
