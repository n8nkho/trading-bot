"""Alpaca execution helpers — broker-side bracket OCO for Classic stock entries."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

ALPACA_BRACKET_MIN_OFFSET = 0.01


def bracket_exits_enabled() -> bool:
    return str(os.environ.get("FORTRESS_BRACKET_EXITS", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _normalize_move_pct(value: float) -> float:
    """Return positive fractional price move (0.02 == 2%)."""
    v = abs(float(value))
    if v >= 1.0:
        return v / 100.0
    return v


def classic_bracket_prices(
    *,
    entry_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple[float, float]:
    """Return (take_profit_price, stop_loss_price) for a long stock entry."""
    ep = float(entry_price)
    sl_frac = _normalize_move_pct(stop_loss_pct)
    tp_frac = _normalize_move_pct(take_profit_pct)
    tp = round(ep * (1.0 + tp_frac), 2)
    sl = round(ep * (1.0 - sl_frac), 2)
    return clamp_bracket_prices(side="long", base_price=ep, take_profit=tp, stop_loss=sl)


def clamp_bracket_prices(
    *,
    side: str,
    base_price: float,
    take_profit: float,
    stop_loss: float,
    min_offset: float = ALPACA_BRACKET_MIN_OFFSET,
) -> tuple[float, float]:
    side = side.lower()
    bp = round(float(base_price), 2)
    tp = round(float(take_profit), 2)
    sl = round(float(stop_loss), 2)
    tick = max(0.01, float(min_offset))
    if side == "long":
        sl = min(sl, round(bp - tick, 2))
        tp = max(tp, round(bp + tick, 2))
    else:
        sl = max(sl, round(bp + tick, 2))
        tp = min(tp, round(bp - tick, 2))
    return tp, sl


def submit_entry_with_bracket(
    *,
    client: Any,
    symbol: str,
    qty: int,
    entry_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> dict[str, Any]:
    """Submit long stock entry with broker-side bracket when enabled."""
    if client is None:
        return {"success": False, "error": "Alpaca client not initialized"}

    sym = str(symbol or "").upper()
    use_bracket = bracket_exits_enabled()
    tp_px, sl_px = classic_bracket_prices(
        entry_price=entry_price,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )

    try:
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            MarketOrderRequest,
            StopLossRequest,
            TakeProfitRequest,
        )

        tp_req = TakeProfitRequest(limit_price=tp_px)
        sl_req = StopLossRequest(stop_price=sl_px)

        if use_bracket:
            req = MarketOrderRequest(
                symbol=sym,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                take_profit=tp_req,
                stop_loss=sl_req,
            )
            order_type = "bracket_market"
        else:
            req = MarketOrderRequest(
                symbol=sym,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            order_type = "market"

        order = client.submit_order(req)
        return {
            "success": True,
            "order_id": str(order.id),
            "filled_qty": int(order.filled_qty) if order.filled_qty else None,
            "filled_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            "status": str(order.status),
            "error": None,
            "order_type": order_type,
            "take_profit_price": tp_px if use_bracket else None,
            "stop_loss_price": sl_px if use_bracket else None,
        }
    except Exception as e:
        logger.warning("%s: bracket submit failed: %s — falling back to market", sym, e)
        try:
            from alpaca.trading.enums import OrderSide, TimeInForce
            from alpaca.trading.requests import MarketOrderRequest

            order = client.submit_order(
                MarketOrderRequest(
                    symbol=sym,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                )
            )
            return {
                "success": True,
                "order_id": str(order.id),
                "filled_qty": int(order.filled_qty) if order.filled_qty else None,
                "filled_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "status": str(order.status),
                "error": None,
                "order_type": "market_fallback",
            }
        except Exception as e2:
            return {
                "success": False,
                "order_id": None,
                "filled_qty": None,
                "filled_price": None,
                "error": f"{type(e2).__name__}: {e2}",
            }
