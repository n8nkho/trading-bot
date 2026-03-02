#!/usr/bin/env python3
"""Submit a few tiny Alpaca PAPER test buy orders (<= $10 notional each)."""
import logging
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


MAX_ORDERS = 4  # 4 tiny test buys ("2-2")
MAX_NOTIONAL_PER_ORDER = 10.0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not base_url or "paper" not in base_url.lower():
        logging.error(f"ALPACA_BASE_URL is not paper trading: {base_url!r}")
        return 1

    if not api_key or not secret_key:
        logging.error("Alpaca credentials not found; aborting test orders.")
        return 1

    try:
        client = TradingClient(api_key, secret_key, paper=True)
        logging.info(f"Alpaca client initialized for PAPER trading at {base_url}")
    except Exception as e:
        logging.error(f"Failed to initialize Alpaca client: {type(e).__name__}: {e}")
        return 1

    # Simple, very liquid tickers; notional keeps us <= $10 each.
    candidates = ["SPY", "QQQ", "TLT", "XLF", "XLE", "XLK", "XLI", "XLB"]

    placed = []

    for ticker in candidates:
        if len(placed) >= MAX_ORDERS:
            break

        try:
            logging.info(f"[TEST] Submitting PAPER BUY for {ticker}: notional=${MAX_NOTIONAL_PER_ORDER:.2f}")
            order = client.submit_order(
                MarketOrderRequest(
                    symbol=ticker,
                    notional=MAX_NOTIONAL_PER_ORDER,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                )
            )
            logging.info(f"[TEST] {ticker}: order submitted id={order.id}, status={order.status}")
            placed.append(
                {
                    "ticker": ticker,
                    "notional": MAX_NOTIONAL_PER_ORDER,
                    "order_id": str(order.id),
                    "status": str(order.status),
                }
            )
        except Exception as e:
            logging.error(f"[TEST] {ticker}: failed to submit test order: {type(e).__name__}: {e}")

    logging.info(f"[TEST] Alpaca test orders placed: {len(placed)}")
    for p in placed:
        logging.info(
            f"[TEST] {p['ticker']}: notional=${p['notional']:.2f}, id={p['order_id']}, status={p['status']}"
        )

    if not placed:
        logging.warning("[TEST] No test orders placed (likely all prices > $10).")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

