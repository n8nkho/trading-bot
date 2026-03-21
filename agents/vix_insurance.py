import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import os
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta

from utils.market_assets import require_market_assets

# Constants
VIX_LOW_THRESHOLD = 15
VIX_HIGH_THRESHOLD = 25
INSURANCE_ALLOCATION_PCT = 0.01
EXPIRATION_DAYS = 30

# Load environment variables
load_dotenv()
api_key = os.getenv("APCA_API_KEY_ID")
secret_key = os.getenv("APCA_API_SECRET_KEY")


def _get_client():
    """
    Lazy Alpaca client creation.
    This prevents import-time crashes when credentials are not present.
    """
    try:
        if not api_key or not secret_key:
            return None
        return TradingClient(api_key, secret_key, paper=True)
    except Exception:
        return None

def get_current_vix():
    try:
        assets = require_market_assets()
        vix_symbol = assets.get("vix_symbol")
        if not vix_symbol:
            return None
        vix_data = yf.Ticker(vix_symbol).history(period="1d")
        current_vix = vix_data['Close'].iloc[-1]
        return float(current_vix)
    except Exception as e:
        logging.error(f"Error fetching VIX data: {e}")
        return None

def should_buy_insurance(portfolio_value, current_vix):
    if current_vix < VIX_LOW_THRESHOLD:
        client = _get_client()
        if client is None:
            return False, "VIX insurance disabled (missing Alpaca credentials)"
        assets = require_market_assets()
        underlying_symbol = (assets.get("vix_insurance") or {}).get("underlying_symbol")
        if not underlying_symbol:
            return False, "VIX insurance disabled (missing underlying_symbol in config/market_assets.json)"
        # Check for existing VIX position
        positions = client.get_open_positions()
        has_vix_position = any(pos.symbol == underlying_symbol for pos in positions)
        insurance_cost = portfolio_value * INSURANCE_ALLOCATION_PCT
        if not has_vix_position:
            return True, f"VIX is low at {current_vix}. No existing insurance. Cost: {insurance_cost}"
    return False, "No need to buy insurance."

def calculate_insurance_position(portfolio_value):
    insurance_amount = portfolio_value * INSURANCE_ALLOCATION_PCT
    assets = require_market_assets()
    underlying_symbol = (assets.get("vix_insurance") or {}).get("underlying_symbol")
    if not underlying_symbol:
        return None

    put_type_label = (assets.get("vix_insurance") or {}).get("put_type_label") or "PUT"
    put_reason_suffix = (assets.get("vix_insurance") or {}).get("put_reason_suffix") or "puts for crash protection"

    underlying_price = yf.Ticker(underlying_symbol).history(period="1d")['Close'].iloc[-1]
    strike_price = underlying_price * 0.95
    expiration_date = (datetime.now() + timedelta(days=EXPIRATION_DAYS)).strftime('%Y-%m-%d')
    contracts = int(insurance_amount / (underlying_price * 100))  # Assuming 100 shares per contract
    return {
        'type': put_type_label,
        'strike': strike_price,
        'expiration': expiration_date,
        'contracts': contracts,
        'cost': insurance_amount,
        'reason': f'5% OTM {underlying_symbol} puts for crash protection' if put_reason_suffix is None else f'5% OTM {underlying_symbol} {put_reason_suffix}'
    }

def check_insurance_payout():
    client = _get_client()
    if client is None:
        return 0
    assets = require_market_assets()
    underlying_symbol = (assets.get("vix_insurance") or {}).get("underlying_symbol")
    if not underlying_symbol:
        return 0
    positions = client.get_open_positions()
    payout = 0
    for pos in positions:
        if pos.symbol == underlying_symbol and pos.side == "short":
            current_price = yf.Ticker(underlying_symbol).history(period="1d")['Close'].iloc[-1]
            if current_price < pos.avg_entry_price:
                payout += (pos.avg_entry_price - current_price) * pos.qty
    return payout

def manage_insurance():
    current_vix = get_current_vix()
    if current_vix is None:
        logging.error("Failed to fetch current VIX.")
        return

    client = _get_client()
    if client is None:
        logging.warning("Skipping VIX insurance management (missing Alpaca credentials).")
        return

    portfolio_value = client.get_account().portfolio_value
    buy_insurance, reason = should_buy_insurance(portfolio_value, current_vix)
    if buy_insurance:
        insurance_position = calculate_insurance_position(portfolio_value)
        logging.info(f"Buying insurance: {insurance_position}")
        # Execute buy order logic here

    payout = check_insurance_payout()
    if payout > 0:
        logging.info(f"Insurance payout: {payout}")
        # Execute sell order logic here
