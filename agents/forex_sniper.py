import datetime
import logging
from oandapyV20 import API
from oandapyV20.endpoints import instruments, orders, accounts
from oandapyV20.contrib.requests import MarketOrderRequest

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# OANDA API setup
OANDA_API_KEY = 'YOUR_OANDA_API_KEY'
OANDA_ACCOUNT_ID = 'YOUR_OANDA_ACCOUNT_ID'
api = API(access_token=OANDA_API_KEY)

# Constants
MAX_TRADES_PER_DAY = 3
MAX_CONSECUTIVE_LOSSES = 2
STOP_LOSS_PIPS = 10
TAKE_PROFIT_PIPS = [10, 20, 30]
RISK_PER_TRADE = 0.005  # 0.5%
TRADING_HOURS = (8, 12)  # 8 AM to 12 PM EST

# State variables
trades_today = 0
consecutive_losses = 0
stop_trading_for_today = False

def find_sniper_setup():
    """Identify potential trade setups based on specified criteria."""
    if stop_trading_for_today:
        logging.info("Trading stopped for today due to consecutive losses.")
        return None

    current_time = datetime.datetime.now().astimezone(datetime.timezone.utc)
    if not (TRADING_HOURS[0] <= current_time.hour < TRADING_HOURS[1]):
        logging.info("Outside of trading hours.")
        return None

    # Check economic calendar for upcoming news (pseudo-code)
    if check_upcoming_news():
        logging.info("Upcoming news event detected. No trades.")
        return None

    # Fetch EUR/USD 15-min chart data (pseudo-code)
    prices = fetch_eur_usd_chart()

    # Calculate RSI and identify support/resistance
    rsi = calculate_rsi(prices, period=14)
    support_resistance = identify_support_resistance(prices, window=100)

    # Check entry criteria
    if check_entry_criteria(prices, rsi, support_resistance):
        return {"setup": "valid setup"}
    return None

def calculate_lot_size(account_balance, stop_pips=STOP_LOSS_PIPS):
    """Calculate the lot size based on account balance and risk."""
    risk_amount = account_balance * RISK_PER_TRADE
    lot_size = risk_amount / stop_pips
    return lot_size

def execute_sniper_trade(setup):
    """Execute a trade based on the identified setup."""
    global trades_today, consecutive_losses

    if trades_today >= MAX_TRADES_PER_DAY:
        logging.info("Max trades reached for today.")
        return

    # Calculate lot size (pseudo-code)
    account_balance = get_account_balance()
    lot_size = calculate_lot_size(account_balance)

    # Submit market order via OANDA (pseudo-code)
    order = MarketOrderRequest(instrument="EUR_USD", units=lot_size)
    response = api.request(orders.OrderCreate(OANDA_ACCOUNT_ID, data=order.data))

    # Set stop loss and take profit levels (pseudo-code)
    set_stop_loss_and_take_profit(response)

    trades_today += 1
    logging.info(f"Trade executed: {response}")

def monitor_sniper_trades():
    """Monitor and manage open trades."""
    # Check open trades every minute (pseudo-code)
    open_trades = get_open_trades()
    for trade in open_trades:
        manage_trade(trade)

    # Check daily limits
    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        global stop_trading_for_today
        stop_trading_for_today = True
        logging.info("Consecutive losses limit reached. Stopping trading for today.")

# Additional helper functions (pseudo-code)
def check_upcoming_news():
    # Implement news checking logic
    return False

def fetch_eur_usd_chart():
    # Implement chart fetching logic
    return []

def calculate_rsi(prices, period):
    # Implement RSI calculation
    return 50

def identify_support_resistance(prices, window):
    # Implement support/resistance identification
    return {"support": [], "resistance": []}

def check_entry_criteria(prices, rsi, support_resistance):
    # Implement entry criteria check
    return True

def get_account_balance():
    # Implement account balance retrieval
    return 10000

def set_stop_loss_and_take_profit(response):
    # Implement stop loss and take profit setting
    pass

def get_open_trades():
    # Implement open trades retrieval
    return []

def manage_trade(trade):
    # Implement trade management logic
    pass
import datetime
import logging
import os
import pytz
import numpy as np
import pandas as pd
import yfinance as yf
from oandapyV20 import API
from oandapyV20.endpoints import orders, accounts
from oandapyV20.contrib.requests import MarketOrderRequest

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# OANDA API setup
OANDA_API_KEY = os.getenv('OANDA_API_KEY')
OANDA_ACCOUNT_ID = os.getenv('OANDA_ACCOUNT_ID')
api = API(access_token=OANDA_API_KEY)

# Global constants
MAX_RISK_PCT = 0.005  # 0.5% risk per trade
STOP_LOSS_PIPS = 10
TARGET_1_PIPS = 10  # Close 50%
TARGET_2_PIPS = 20  # Close 30%
TARGET_3_PIPS = 30  # Close 20%
MAX_TRADES_PER_DAY = 3
MAX_CONSECUTIVE_LOSSES = 2
MAX_HOLD_HOURS = 4
TRADING_PAIR = "EUR_USD"
TIME_WINDOW_START = 8  # 8 AM EST
TIME_WINDOW_END = 12   # 12 PM EST

def is_trading_window():
    """Check if the current time is within the trading window."""
    est = pytz.timezone('US/Eastern')
    current_time = datetime.datetime.now(est)
    if current_time.weekday() < 5 and TIME_WINDOW_START <= current_time.hour < TIME_WINDOW_END:
        logging.info("Trading window: OPEN")
        return True
    logging.info("Trading window: CLOSED")
    return False

def get_eurusd_data(period='1d', interval='15m'):
    """Fetch EUR/USD historical data."""
    try:
        data = yf.download("EURUSD=X", period=period, interval=interval)
        return data
    except Exception as e:
        logging.error(f"Error fetching EUR/USD data: {e}")
        return pd.DataFrame()

def calculate_rsi(data, period=14):
    """Calculate RSI from close prices."""
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def find_support_resistance(data, window=20):
    """Identify support and resistance levels."""
    rolling_min = data['Low'].rolling(window=window).min()
    rolling_max = data['High'].rolling(window=window).max()
    support = rolling_min.iloc[-1]
    resistance = rolling_max.iloc[-1]
    return {'support': support, 'resistance': resistance}

def check_engulfing_pattern(data):
    """Check for bullish or bearish engulfing patterns."""
    last_two = data.iloc[-2:]
    if last_two['Close'].iloc[1] > last_two['Open'].iloc[1] and last_two['Close'].iloc[0] < last_two['Open'].iloc[0]:
        return "BULLISH"
    elif last_two['Close'].iloc[1] < last_two['Open'].iloc[1] and last_two['Close'].iloc[0] > last_two['Open'].iloc[0]:
        return "BEARISH"
    return None

def check_all_entry_criteria(data, current_price):
    """Check all entry criteria for a trade setup."""
    rsi = calculate_rsi(data)
    levels = find_support_resistance(data)
    pattern = check_engulfing_pattern(data)
    if pattern and abs(current_price - levels['support']) <= 0.0005:
        return {
            'signal': 'BUY' if pattern == "BULLISH" else 'SELL',
            'entry_price': current_price,
            'stop_loss': current_price - 0.001 if pattern == "BULLISH" else current_price + 0.001,
            'take_profit_1': current_price + 0.001 if pattern == "BULLISH" else current_price - 0.001,
            'take_profit_2': current_price + 0.002 if pattern == "BULLISH" else current_price - 0.002,
            'take_profit_3': current_price + 0.003 if pattern == "BULLISH" else current_price - 0.003,
            'reason': f"Engulfing pattern with RSI {rsi}"
        }
    return None

def calculate_position_size(account_balance, stop_pips=10):
    """Calculate the position size based on account balance and risk."""
    risk_amount = account_balance * MAX_RISK_PCT
    pip_value = 0.0001  # Standard pip value for EUR/USD
    lot_size = risk_amount / (stop_pips * pip_value * 100000)
    return round(lot_size, 3)

def get_account_balance():
    """Retrieve the current account balance from OANDA."""
    try:
        response = api.request(accounts.AccountSummary(OANDA_ACCOUNT_ID))
        return float(response['account']['balance'])
    except Exception as e:
        logging.error(f"Error retrieving account balance: {e}")
        return 0.0

def execute_trade(signal_dict, lot_size):
    """Execute a trade based on the signal."""
    try:
        order = MarketOrderRequest(instrument=TRADING_PAIR, units=lot_size)
        response = api.request(orders.OrderCreate(OANDA_ACCOUNT_ID, data=order.data))
        logging.info(f"Trade executed: {response}")
        return response
    except Exception as e:
        logging.error(f"Error executing trade: {e}")
        return None

def find_sniper_setup():
    """Identify and execute a valid trade setup."""
    if not is_trading_window():
        return None
    data = get_eurusd_data()
    if data.empty:
        return None
    current_price = data['Close'].iloc[-1]
    signal = check_all_entry_criteria(data, current_price)
    if signal:
        account_balance = get_account_balance()
        lot_size = calculate_position_size(account_balance)
        execute_trade(signal, lot_size)
        return signal
    return None

def monitor_open_trades():
    """Monitor and manage open trades."""
    # This function would include logic to manage open trades, such as checking for take profit levels
    # and adjusting stop losses. This is a placeholder for the actual implementation.
    pass

def check_daily_limits():
    """Check if daily trading limits have been reached."""
    # This function would include logic to track the number of trades and consecutive losses.
    # It would save and load this data from a file to persist state across sessions.
    pass
