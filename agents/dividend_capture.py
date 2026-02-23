import yfinance as yf
import pandas as pd
import logging
from datetime import datetime, timedelta
import os

# Constants
MIN_DIVIDEND_YIELD = 0.004  # 0.4% quarterly minimum
MAX_HOLD_DAYS = 3
CAPTURE_ALLOCATION_PCT = 0.10  # 10% of portfolio
SAFE_TICKERS = ['JPM', 'JNJ', 'PG', 'KO', 'PEP', 'XOM', 'CVX', 'WMT', 'HD', 'T']

def load_dividend_calendar():
    """Load and parse the dividend calendar."""
    file_path = 'data/dividend_calendar.csv'
    if os.path.exists(file_path):
        df = pd.read_csv(file_path)
        df['ex_date'] = pd.to_datetime(df['ex_date'])
        upcoming_dividends = df[df['ex_date'] <= datetime.now() + timedelta(days=5)]
        return upcoming_dividends.to_dict('records')
    return []

def get_stock_info(ticker):
    """Get stock information using yfinance."""
    stock = yf.Ticker(ticker)
    info = stock.info
    return {
        'ticker': ticker,
        'price': info['currentPrice'],
        'volume': info['volume'],
        'sector': info['sector']
    }

def calculate_dividend_return(dividend_amount, stock_price):
    """Calculate the net expected dividend return."""
    dividend_yield = (dividend_amount / stock_price) * 100
    expected_price_drop = 0.4  # Typical 0.3-0.5%
    net_expected = dividend_yield - expected_price_drop
    return net_expected

def select_best_dividend_opportunity(calendar_list):
    """Select the best dividend opportunity."""
    filtered = [entry for entry in calendar_list if entry['ticker'] in SAFE_TICKERS]
    filtered = [entry for entry in filtered if calculate_dividend_return(entry['dividend_amount'], get_stock_info(entry['ticker'])['price']) > MIN_DIVIDEND_YIELD]
    filtered = [entry for entry in filtered if get_stock_info(entry['ticker'])['volume'] > 1_000_000]
    filtered.sort(key=lambda x: (calculate_dividend_return(x['dividend_amount'], get_stock_info(x['ticker'])['price']), get_stock_info(x['ticker'])['volume']), reverse=True)
    return filtered[:2]

def calculate_dividend_position(ticker, portfolio_value, stock_price, dividend_amount):
    """Calculate the dividend position."""
    allocation = portfolio_value * CAPTURE_ALLOCATION_PCT
    shares = int(allocation / stock_price)
    expected_dividend = shares * dividend_amount
    expected_return_pct = calculate_dividend_return(dividend_amount, stock_price)
    return {
        'ticker': ticker,
        'shares': shares,
        'cost': shares * stock_price,
        'expected_dividend': expected_dividend,
        'expected_return_pct': expected_return_pct
    }

def dividend_capture_strategy(portfolio_value):
    """Implement the dividend capture strategy."""
    calendar = load_dividend_calendar()
    if not calendar:
        logging.info("No upcoming dividends found.")
        return None
    best_opportunities = select_best_dividend_opportunity(calendar)
    recommendations = []
    for opportunity in best_opportunities:
        stock_info = get_stock_info(opportunity['ticker'])
        position = calculate_dividend_position(opportunity['ticker'], portfolio_value, stock_info['price'], opportunity['dividend_amount'])
        recommendations.append(position)
        logging.info(f"Recommendation: {position}")
    return recommendations

def create_sample_calendar():
    """Create a sample dividend calendar."""
    sample_data = [
        {'ticker': 'JPM', 'ex_date': '2026-03-15', 'dividend_amount': 1.00},
        {'ticker': 'JNJ', 'ex_date': '2026-03-20', 'dividend_amount': 1.13},
        {'ticker': 'PG', 'ex_date': '2026-03-25', 'dividend_amount': 0.94}
    ]
    df = pd.DataFrame(sample_data)
    os.makedirs('data', exist_ok=True)
    df.to_csv('data/dividend_calendar.csv', index=False)
