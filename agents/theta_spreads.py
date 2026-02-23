import yfinance as yf
import logging
from datetime import datetime, timedelta

# Constants
SPREAD_WIDTH = 5
TARGET_DTE = 30

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_spy_price():
    try:
        ticker = yf.Ticker("SPY")
        data = ticker.history(period='1d')
        return data['Close'].iloc[-1]
    except Exception as e:
        logging.error(f"Error fetching SPY price: {e}")
        return None

def design_bull_put_spread(spy_price):
    try:
        # Placeholder for fetching options chain
        # options_chain = fetch_options_chain("SPY", TARGET_DTE)
        
        sell_strike = round(spy_price * 0.95, 2)
        buy_strike = sell_strike - SPREAD_WIDTH
        
        # Placeholder for premiums
        sell_premium = 1.0  # Example premium
        buy_premium = 0.5   # Example premium
        
        net_credit = sell_premium - buy_premium
        
        return {
            "sell_strike": sell_strike,
            "buy_strike": buy_strike,
            "sell_premium": sell_premium,
            "buy_premium": buy_premium,
            "net_credit": net_credit
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
        
        spread_cost = SPREAD_WIDTH - spread_details['net_credit']
        quantity = int((portfolio_value * 0.03) / spread_cost)
        
        logging.info(f"Recommended bull put spread: {spread_details}, Quantity: {quantity}")
        
        return {
            "spread_details": spread_details,
            "quantity": quantity
        }
    except Exception as e:
        logging.error(f"Error in theta strategy: {e}")
        return None
