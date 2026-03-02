#!/usr/bin/env python3
"""Place 2 Alpaca paper test orders, <= $10 each, <= $100 total. Cancel manually if needed."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

MAX_PER_ORDER = 10.0   # $10 per order
MAX_TOTAL = 100.0     # $100 total

def main():
    if "paper" not in (BASE_URL or "").lower():
        print("ERROR: Use paper trading URL only.")
        return 1
    if not API_KEY or not SECRET:
        print("ERROR: ALPACA_API_KEY / ALPACA_SECRET_KEY not set.")
        return 1
    client = TradingClient(API_KEY, SECRET, paper=True)
    # 2 orders, $10 notional each
    orders_spec = [
        ("SPY", 10.0),
        ("QQQ", 10.0),
    ]
    total = sum(n for _, n in orders_spec)
    if total > MAX_TOTAL:
        print(f"ERROR: Total {total} > {MAX_TOTAL}")
        return 1
    for symbol, notional in orders_spec:
        if notional > MAX_PER_ORDER:
            print(f"SKIP {symbol}: ${notional} > ${MAX_PER_ORDER}")
            continue
        try:
            req = MarketOrderRequest(
                symbol=symbol,
                notional=round(notional, 2),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            order = client.submit_order(req)
            print(f"OK {symbol}: order_id={order.id} status={order.status} notional=${notional}")
        except Exception as e:
            print(f"FAIL {symbol}: {e}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
