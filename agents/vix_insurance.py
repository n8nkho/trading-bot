import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import os
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta

# Constants
VIX_LOW_THRESHOLD = 15
VIX_HIGH_THRESHOLD = 25
INSURANCE_ALLOCATION_PCT = 0.01
EXPIRATION_DAYS = 30

# Load environment variables
load_dotenv()

def get_client():
    """Get Alpaca trading client."""
    import os
    from alpaca.trading.client import TradingClient
    api_key = os.getenv('ALPACA_API_KEY')
    secret_key = os.getenv('ALPACA_SECRET_KEY')
    return TradingClient(api_key, secret_key, paper=True)

def get_current_vix():
    try:
        vix_data = yf.Ticker("^VIX").history(period="1d")
        current_vix = vix_data['Close'].iloc[-1]
        return float(current_vix)
    except Exception as e:
        logging.error(f"Error fetching VIX data: {e}")
        return None

def should_buy_insurance(portfolio_value, current_vix):
    if current_vix < VIX_LOW_THRESHOLD:
        # Check for existing VIX position
        client = get_client()
        positions = client.get_open_positions()
        has_vix_position = any(pos.symbol == "SPY" for pos in positions)
        insurance_cost = portfolio_value * INSURANCE_ALLOCATION_PCT
        if not has_vix_position:
            return True, f"VIX is low at {current_vix}. No existing insurance. Cost: {insurance_cost}"
    return False, "No need to buy insurance."

def calculate_insurance_position(portfolio_value):
    insurance_amount = portfolio_value * INSURANCE_ALLOCATION_PCT
    spy_price = yf.Ticker("SPY").history(period="1d")['Close'].iloc[-1]
    strike_price = spy_price * 0.95
    expiration_date = (datetime.now() + timedelta(days=EXPIRATION_DAYS)).strftime('%Y-%m-%d')
    contracts = int(insurance_amount / (spy_price * 100))  # Assuming 100 shares per contract
    return {
        'type': 'SPY_PUT',
        'strike': strike_price,
        'expiration': expiration_date,
        'contracts': contracts,
        'cost': insurance_amount,
        'reason': '5% OTM SPY puts for crash protection'
    }

def check_insurance_payout():
    client = get_client()
    positions = client.get_open_positions()
    payout = 0
    for pos in positions:
        if pos.symbol == "SPY" and pos.side == "short":
            current_price = yf.Ticker("SPY").history(period="1d")['Close'].iloc[-1]
            if current_price < pos.avg_entry_price:
                payout += (pos.avg_entry_price - current_price) * pos.qty
    return payout

def manage_insurance():
    current_vix = get_current_vix()
    if current_vix is None:
        logging.error("Failed to fetch current VIX.")
        return

    client = get_client()
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
