import yfinance as yf
import logging
from datetime import datetime, timedelta

from utils.market_assets import require_market_assets

# Constants
SPREAD_WIDTH = 5
TARGET_DTE = 30

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_spy_price():
    try:
        assets = require_market_assets()
        underlying_symbol = (assets.get("theta_spreads") or {}).get("underlying_symbol")
        if not underlying_symbol:
            return None
        ticker = yf.Ticker(underlying_symbol)
        data = ticker.history(period='1d')
        return data['Close'].iloc[-1]
    except Exception as e:
        logging.error(f"Error fetching theta underlying price: {e}")
        return None

def design_bull_put_spread(spy_price):
    try:
        assets = require_market_assets()
        underlying_symbol = (assets.get("theta_spreads") or {}).get("underlying_symbol")
        if not underlying_symbol:
            return None
        ticker = yf.Ticker(underlying_symbol)
        expirations = ticker.options
        target_date = datetime.now() + timedelta(days=TARGET_DTE)
        expiration = min(expirations, key=lambda date: abs(datetime.strptime(date, '%Y-%m-%d') - target_date))
        
        options_chain = ticker.option_chain(expiration).puts
        sell_strike = round(spy_price * 0.95, 2)
        sell_option = options_chain[options_chain['strike'] == sell_strike]
        
        if sell_option.empty:
            logging.error("No suitable sell option found.")
            return None
        
        sell_premium = sell_option['lastPrice'].values[0]
        buy_strike = sell_strike - SPREAD_WIDTH
        buy_option = options_chain[options_chain['strike'] == buy_strike]
        
        if buy_option.empty:
            logging.error("No suitable buy option found.")
            return None
        
        buy_premium = buy_option['lastPrice'].values[0]
        net_credit = sell_premium - buy_premium
        max_risk = SPREAD_WIDTH - net_credit
        
        return {
            "sell_strike": sell_strike,
            "buy_strike": buy_strike,
            "sell_premium": sell_premium,
            "buy_premium": buy_premium,
            "net_credit": net_credit,
            "max_risk": max_risk
        }
    except Exception as e:
        logging.error(f"Error designing bull put spread: {e}")
        return None

def theta_strategy(portfolio_value):
    try:
        spy_price = get_spy_price()
        if spy_price is None:
            return None
        
        spread_details = design_bull_put_spread(spy_price)
        if spread_details is None:
            return None
        
        max_risk = spread_details['max_risk']
        quantity = min(int((portfolio_value * 0.03) / max_risk), 3)
        
        logging.info(f"Recommended bull put spread: {spread_details}, Quantity: {quantity}")
        
        return {
            "spread_details": spread_details,
            "quantity": quantity
        }
    except Exception as e:
        logging.error(f"Error in theta strategy: {e}")
        return None
def should_open_spread():
    try:
        # Simple readiness check
        return True, "Ready"
    except Exception as e:
        logging.error(f"Error in readiness check: {e}")
        return False, str(e)
