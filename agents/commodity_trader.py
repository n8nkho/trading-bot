import os
import logging
import yfinance as yf
from oandapyV20 import API
from oandapyV20.endpoints.pricing import PricingInfo
from agents.vix_insurance import get_current_vix

# Constants
GOLD_PAIR = "XAU_USD"
SILVER_PAIR = "XAG_USD"
COMMODITY_ALLOCATION_PCT = 0.08  # 8% of portfolio
USD_STRENGTH_THRESHOLD = 95  # DXY level

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OANDA API setup
oanda_api = API(access_token=os.getenv("OANDA_API_KEY"))

def get_usd_strength():
    try:
        dxy = yf.Ticker("DX-Y.NYB")
        dxy_price = dxy.history(period="1d")['Close'].iloc[-1]
        return float(dxy_price)
    except Exception as e:
        logger.error(f"Failed to get USD strength: {e}")
        return None

def get_gold_price():
    try:
        params = {"instruments": GOLD_PAIR}
        r = PricingInfo(accountID=os.getenv("OANDA_ACCOUNT_ID"), params=params)
        response = oanda_api.request(r)
        gold_price = float(response['prices'][0]['bids'][0]['price'])
        return gold_price
    except Exception as e:
        logger.error(f"Failed to get gold price: {e}")
        return None

def get_silver_price():
    try:
        params = {"instruments": SILVER_PAIR}
        r = PricingInfo(accountID=os.getenv("OANDA_ACCOUNT_ID"), params=params)
        response = oanda_api.request(r)
        silver_price = float(response['prices'][0]['bids'][0]['price'])
        return silver_price
    except Exception as e:
        logger.error(f"Failed to get silver price: {e}")
        return None

def should_buy_commodities(usd_strength, vix_level):
    if usd_strength is None:
        return "HOLD", "USD strength data unavailable"
    
    if usd_strength < 90:
        return "BUY_BOTH", "USD very weak (DXY < 90)"
    elif usd_strength < USD_STRENGTH_THRESHOLD and vix_level > 25:
        return "BUY_GOLD", "USD weak and VIX > 25"
    elif usd_strength < USD_STRENGTH_THRESHOLD and vix_level > 20:
        return "BUY_GOLD", "USD weak and VIX > 20"
    elif usd_strength < USD_STRENGTH_THRESHOLD and vix_level < 25:
        return "BUY_SILVER", "USD weak and VIX < 25 (industrial demand)"
    else:
        return "HOLD", "No favorable conditions"

def calculate_commodity_position(portfolio_value, commodity_type):
    allocation = portfolio_value * COMMODITY_ALLOCATION_PCT
    if commodity_type == "GOLD":
        gold_price = get_gold_price()
        if gold_price is None:
            return None
        lot_size = allocation / gold_price
        stop_price = gold_price * 0.99
        target_price = gold_price * 1.02
        return {
            'pair': GOLD_PAIR,
            'direction': 'BUY',
            'lot_size': lot_size,
            'stop_price': stop_price,
            'target_price': target_price
        }
    elif commodity_type == "SILVER":
        silver_price = get_silver_price()
        if silver_price is None:
            return None
        lot_size = allocation / silver_price
        stop_price = silver_price * 0.98
        target_price = silver_price * 1.04
        return {
            'pair': SILVER_PAIR,
            'direction': 'BUY',
            'lot_size': lot_size,
            'stop_price': stop_price,
            'target_price': target_price
        }
    return None

def commodity_hedge_strategy(portfolio_value):
    usd_strength = get_usd_strength()
    vix_level = get_current_vix()
    action, reasoning = should_buy_commodities(usd_strength, vix_level)
    logger.info(f"Decision: {action}, Reason: {reasoning}")
    
    if action == "BUY_GOLD":
        position = calculate_commodity_position(portfolio_value, "GOLD")
        logger.info(f"Gold position: {position}")
        return position
    elif action == "BUY_SILVER":
        position = calculate_commodity_position(portfolio_value, "SILVER")
        logger.info(f"Silver position: {position}")
        return position
    elif action == "BUY_BOTH":
        gold_position = calculate_commodity_position(portfolio_value / 2, "GOLD")
        silver_position = calculate_commodity_position(portfolio_value / 2, "SILVER")
        logger.info(f"Gold position: {gold_position}, Silver position: {silver_position}")
        return gold_position, silver_position
    else:
        return None
