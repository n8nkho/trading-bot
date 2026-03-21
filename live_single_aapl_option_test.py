import json
import os
import time
from datetime import datetime, timedelta

import yfinance as yf
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from utils.option_contract_schema import format_option_symbol


def _ensure_data_dir():
    os.makedirs("data", exist_ok=True)


def _load_positions_file(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print(f"[live-test] WARNING: positions.json at {path} is not valid JSON; starting fresh.")
        return []
    if isinstance(data, dict):
        return data.get("positions", [])
    return data


def _save_positions_file(path: str, positions):
    with open(path, "w") as f:
        json.dump(positions, f, indent=2)


def main():
    load_dotenv()

    alpaca_api_key = os.getenv("ALPACA_API_KEY")
    alpaca_secret_key = os.getenv("ALPACA_SECRET_KEY")
    alpaca_base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not alpaca_api_key or not alpaca_secret_key:
        raise SystemExit("Missing ALPACA_API_KEY / ALPACA_SECRET_KEY in environment/.env")
    if alpaca_base_url and "paper" not in alpaca_base_url.lower():
        raise SystemExit("Safety check: ALPACA_BASE_URL must contain 'paper'")

    # Use configured watchlist ticker (no hard-coded tickers in this script).
    with open("config/watchlist.json", "r") as f:
        quality_stocks = json.load(f).get("quality_stocks") or []
    if not quality_stocks:
        raise SystemExit("No tickers found in config/watchlist.json (quality_stocks empty).")
    ticker = str(quality_stocks[0].get("ticker")).strip().upper()
    qty_contracts = 1

    stock = yf.Ticker(ticker)
    hist = stock.history(period="1d")
    if hist.empty:
        raise SystemExit(f"Failed to fetch current {ticker} price from yfinance")
    current_price = float(hist["Close"].iloc[-1])

    # Choose an expiration 30-45 DTE (fallback to closest to 35 DTE)
    expirations = stock.options or []
    if not expirations:
        raise SystemExit(f"No options expirations available for {ticker} from yfinance")

    def dte(exp):
        dt = datetime.strptime(exp, "%Y-%m-%d")
        return (dt - datetime.now()).days

    in_range = [exp for exp in expirations if 30 <= dte(exp) <= 45]
    if in_range:
        target_exp = min(in_range, key=lambda e: abs(dte(e) - 35))
    else:
        target_exp = min(expirations, key=lambda e: abs(dte(e) - 35))

    chain = stock.option_chain(target_exp)
    calls = chain.calls
    if calls is None or calls.empty:
        raise SystemExit("No calls chain data available")

    # Pick the call strike closest to current price.
    # yfinance occasionally returns NaN pricing for a single strike, so we try several nearest strikes.
    sorted_candidates = calls.iloc[(calls["strike"] - current_price).abs().argsort()[:7]]

    strike = None
    premium = None
    premium_last = None
    premium_ask = None
    premium_bid = None

    def _nan_ok(x):
        # NaN is not equal to itself.
        return x is not None and x == x

    # Prefer ask for a faster fill, but keep a tiny discount to allow cancelability.
    for _, row in sorted_candidates.iterrows():
        s = float(row.get("strike"))
        pl = row.get("lastPrice")
        pa = row.get("ask")
        pb = row.get("bid")

        candidate_premium = None
        pa_ok = _nan_ok(pa) and float(pa) > 0
        pl_ok = _nan_ok(pl) and float(pl) > 0
        pb_ok = _nan_ok(pb) and float(pb) > 0

        # Prefer ask for a faster fill, but ensure it's strictly > 0.
        if pa_ok:
            candidate_premium = float(pa)
        elif pl_ok:
            candidate_premium = float(pl)
        elif pb_ok and pa_ok:
            candidate_premium = float(pb + pa) / 2.0

        if candidate_premium is not None and candidate_premium > 0:
            strike = s
            premium_last = pl
            premium_ask = pa
            premium_bid = pb
            premium = candidate_premium
            break

    if premium is None or premium <= 0 or strike is None:
        raise SystemExit("Could not derive a valid option premium from nearest strikes (NaN or <= 0)")

    # Slightly below ask to preserve manual cancel option.
    limit_price = round(max(0.01, premium * 0.995), 2)
    expiration_date = target_exp  # already YYYY-MM-DD
    call = True

    option_symbol = format_option_symbol(
        underlying_ticker=ticker,
        expiration=expiration_date,
        strike=strike,
        call=call,
    )

    print(f"[live-test] Submitting {ticker} call (paper) limit order")
    print(f"[live-test] underlying={ticker} strike={strike} exp={expiration_date} option_symbol={option_symbol}")
    print(f"[live-test] current_price≈{current_price:.2f} premium≈{premium:.2f} limit_price={limit_price} qty_contracts={qty_contracts}")

    alpaca_client = TradingClient(alpaca_api_key, alpaca_secret_key, paper=True)

    existing_open = None
    allow_new_order = os.getenv("LIVE_TEST_ALLOW_NEW_ORDER", "0") == "1"
    cancel_after_seconds = float(os.getenv("LIVE_TEST_CANCEL_AFTER_SECONDS", "0") or "0")
    try:
        # Prefer filtered lookup by symbol if supported by this client version.
        existing = alpaca_client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[option_symbol])
        )
        # existing may be list of orders
        if isinstance(existing, list) and existing:
            existing_open = existing[0]
    except Exception:
        # If symbol filtering isn't available, fall back to scanning all orders.
        pass

    if existing_open is not None:
        order = existing_open
        print(f"[live-test] found existing OPEN order for symbol={option_symbol}; order_id={order.id}")
    else:
        if not allow_new_order:
            order = None
            print(f"[live-test] no existing OPEN order found for symbol={option_symbol}")
            print(f"[live-test] LIVE_TEST_ALLOW_NEW_ORDER is not enabled; skipping new order submission.")
        else:
            order_req = LimitOrderRequest(
                symbol=option_symbol,
                qty=qty_contracts,
                side=OrderSide.BUY,
                type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_price,
            )

            order = alpaca_client.submit_order(order_req)
            print(f"[live-test] submitted order_id={order.id} status={getattr(order, 'status', None)}")

    # Write a position record so we can run exit_monitor decisions safely (no execution).
    if order is not None and cancel_after_seconds > 0:
        try:
            print(f"[live-test] waiting {cancel_after_seconds:.1f}s then cancelling order_id={order.id}")
            time.sleep(cancel_after_seconds)
            # alpaca-py uses `cancel_order_by_id` in this version.
            alpaca_client.cancel_order_by_id(str(order.id))
            print(f"[live-test] cancel requested for order_id={order.id}")
        except Exception as e:
            print(f"[live-test] WARNING: cancel_order failed for order_id={order.id}: {type(e).__name__}: {e}")

    _ensure_data_dir()
    positions_path = os.path.join("data", "positions.json")
    positions = _load_positions_file(positions_path)

    # Use limit_price as entry premium proxy for schema/exit testing.
    option_position = {
        "ticker": option_symbol,  # option contract symbol
        "type": "OPTION",
        "underlying_ticker": ticker,
        "qty": qty_contracts,
        "entry_premium": limit_price,
        "expiration_date": expiration_date,
        "strike": strike,
        "call": call,
        "entry_date": datetime.now().isoformat(),
        # Convert UUIDs to strings for JSON serialization.
        "order_id": str(getattr(order, "id", None)) if order is not None and getattr(order, "id", None) is not None else None,
        "sector": "Unknown",
        "stop_loss_pct": -2.0,
        "take_profit_pct": 15.0,
        "tiers_sold": {"tier1": False, "tier2": False, "tier3": False},
    }

    positions.append(option_position)
    _save_positions_file(positions_path, positions)

    # Validate exit_monitor schema/logic only (decisions, no sell execution).
    from agents.exit_monitor import monitor_positions

    print("[live-test] running exit_monitor.monitor_positions([option_position]) (DECISIONS ONLY)")
    decisions = monitor_positions([option_position])
    for d in decisions:
        print("[live-test] exit_decision:", {k: d.get(k) for k in ["ticker", "action", "tier", "sell_qty", "reason"]})

    print("[live-test] Done. If your Alpaca order is still open, cancel it manually.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

