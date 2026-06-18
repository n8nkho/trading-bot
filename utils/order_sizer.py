"""Exit order sizing — chunk large sells under FORTRESS_MAX_ORDER_NOTIONAL_USD."""
from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

CHUNK_DELAY_MIN_SEC = 0.1
CHUNK_DELAY_MAX_SEC = 0.5


def max_order_notional_usd() -> float:
    try:
        return float(os.environ.get("FORTRESS_MAX_ORDER_NOTIONAL_USD", "25000"))
    except ValueError:
        return 25000.0


def chunk_qtys(total_qty: int, px: float, max_notional_usd: float | None = None) -> list[int]:
    """Split total_qty into order chunks that each fit under max_notional_usd."""
    if total_qty <= 0:
        return []
    cap = max_notional_usd if max_notional_usd is not None else max_order_notional_usd()
    if px <= 0:
        return [total_qty]
    max_per = max(1, int(cap // float(px)))
    chunks: list[int] = []
    remaining = int(total_qty)
    while remaining > 0:
        q = min(remaining, max_per)
        chunks.append(q)
        remaining -= q
    return chunks


def chunk_exit_delay_sec() -> float:
    return random.uniform(CHUNK_DELAY_MIN_SEC, CHUNK_DELAY_MAX_SEC)


def plan_chunked_exit(shares: int, mark_price: float) -> dict[str, Any]:
    """Plan exit order quantities under the notional cap."""
    try:
        qty = int(abs(float(shares or 0)))
    except (TypeError, ValueError):
        qty = 0
    try:
        px = float(mark_price or 0)
    except (TypeError, ValueError):
        px = 0.0

    cap = max_order_notional_usd()
    result: dict[str, Any] = {
        "order_qtys": [],
        "chunked_exit": False,
        "max_notional_usd": cap,
        "total_qty": qty,
        "mark_price": px,
    }
    if qty <= 0:
        result["block_reason"] = "invalid_qty"
        return result
    if px <= 0:
        result["order_qtys"] = [qty]
        return result

    order_qtys = chunk_qtys(qty, px, max_notional_usd=cap)
    if not order_qtys:
        result["block_reason"] = "invalid_chunk_qty"
        return result
    if len(order_qtys) > 1:
        result["chunked_exit"] = True
        result["chunk_count"] = len(order_qtys)
        logger.info(
            "chunked_exit:%s qty=%d px=%.2f cap=%.2f chunks=%d",
            "plan",
            qty,
            px,
            cap,
            len(order_qtys),
        )
    result["order_qtys"] = order_qtys
    return result


def submit_chunked_sell_orders(
    ticker: str,
    shares: int,
    mark_price: float,
    *,
    submit_one: Callable[[str, int], dict[str, Any]],
) -> dict[str, Any]:
    """
    Submit one or more sell orders under the notional cap.

    submit_one(ticker, qty) -> result dict with success, order_id, filled_qty, filled_price, error.
    """
    plan = plan_chunked_exit(shares, mark_price)
    if plan.get("block_reason"):
        return {
            "success": False,
            "order_id": None,
            "filled_qty": None,
            "filled_price": None,
            "error": plan.get("block_reason"),
            "chunked_exit": False,
        }

    order_qtys = plan.get("order_qtys") or []
    submitted: list[dict[str, Any]] = []
    total_filled = 0
    last_price = None
    last_order_id = None

    for i, chunk_qty in enumerate(order_qtys):
        if i > 0 and plan.get("chunked_exit"):
            time.sleep(chunk_exit_delay_sec())
        res = submit_one(ticker, chunk_qty)
        submitted.append(res)
        if not res.get("success"):
            return {
                **res,
                "chunked_exit": bool(plan.get("chunked_exit")),
                "chunk_count": len(order_qtys),
                "chunks_submitted": i,
                "submitted": submitted,
            }
        try:
            total_filled += int(res.get("filled_qty") or chunk_qty or 0)
        except (TypeError, ValueError):
            total_filled += chunk_qty
        last_price = res.get("filled_price")
        last_order_id = res.get("order_id")

    return {
        "success": True,
        "order_id": last_order_id,
        "filled_qty": total_filled,
        "filled_price": last_price,
        "error": None,
        "chunked_exit": bool(plan.get("chunked_exit")),
        "chunk_count": len(order_qtys),
        "submitted": submitted,
    }
