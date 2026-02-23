import yfinance as yf
import numpy as np
import pandas as pd
import logging
from datetime import datetime, timedelta
from scipy import stats

# Constants
PAIRS_ALLOCATION_PCT = 0.10  # 10% total (5% each side)
CORRELATION_THRESHOLD = 0.70  # Pairs must be 70%+ correlated
SPREAD_ENTRY_ZSCORE = 2.0  # Enter when 2 std devs from mean
SPREAD_EXIT_ZSCORE = 0.5  # Exit when normalizes
LOOKBACK_DAYS = 60

PREDEFINED_PAIRS = [
    ('AAPL', 'MSFT'),  # Tech giants
    ('JPM', 'BAC'),    # Big banks
    ('XOM', 'CVX'),    # Energy
    ('HD', 'LOW'),     # Home improvement
    ('KO', 'PEP')      # Beverages
]

def get_price_history(ticker, days=60):
    try:
        data = yf.download(ticker, period=f'{days}d')
        return data['Close']
    except Exception as e:
        logging.error(f"Error fetching price history for {ticker}: {e}")
        return None

def calculate_correlation(ticker1, ticker2, days=60):
    prices1 = get_price_history(ticker1, days)
    prices2 = get_price_history(ticker2, days)
    if prices1 is not None and prices2 is not None:
        correlation = prices1.corr(prices2)
        return correlation
    return None

def calculate_spread_zscore(ticker1, ticker2, days=60):
    prices1 = get_price_history(ticker1, days)
    prices2 = get_price_history(ticker2, days)
    if prices1 is not None and prices2 is not None:
        ratio = prices1 / prices2
        mean = ratio.mean()
        std = ratio.std()
        current_ratio = ratio.iloc[-1]
        z_score = (current_ratio - mean) / std
        return z_score
    return None

def find_pair_opportunity():
    best_opportunity = None
    for ticker1, ticker2 in PREDEFINED_PAIRS:
        correlation = calculate_correlation(ticker1, ticker2, LOOKBACK_DAYS)
        if correlation and correlation > CORRELATION_THRESHOLD:
            z_score = calculate_spread_zscore(ticker1, ticker2, LOOKBACK_DAYS)
            if z_score is not None:
                if z_score > SPREAD_ENTRY_ZSCORE:
                    opportunity = {
                        'pair': (ticker1, ticker2),
                        'action': 'SHORT_LONG',
                        'long_ticker': ticker2,
                        'short_ticker': ticker1,
                        'zscore': z_score,
                        'correlation': correlation,
                        'expected_return': '5-10%'
                    }
                elif z_score < -SPREAD_ENTRY_ZSCORE:
                    opportunity = {
                        'pair': (ticker1, ticker2),
                        'action': 'LONG_SHORT',
                        'long_ticker': ticker1,
                        'short_ticker': ticker2,
                        'zscore': z_score,
                        'correlation': correlation,
                        'expected_return': '5-10%'
                    }
                else:
                    continue

                if best_opportunity is None or abs(opportunity['zscore']) > abs(best_opportunity['zscore']):
                    best_opportunity = opportunity

    return best_opportunity

def calculate_pair_position_size(portfolio_value):
    total_allocation = portfolio_value * PAIRS_ALLOCATION_PCT
    long_size = total_allocation / 2
    short_size = total_allocation / 2
    return long_size, short_size

def pairs_trading_strategy(portfolio_value):
    opportunity = find_pair_opportunity()
    if opportunity:
        long_size, short_size = calculate_pair_position_size(portfolio_value)
        long_price = get_price_history(opportunity['long_ticker'], 1).iloc[-1]
        short_price = get_price_history(opportunity['short_ticker'], 1).iloc[-1]
        long_shares = long_size / long_price
        short_shares = short_size / short_price
        recommendation = {
            'opportunity': opportunity,
            'long_shares': long_shares,
            'short_shares': short_shares
        }
        logging.info(f"Pairs trading recommendation: {recommendation}")
        return recommendation
    else:
        logging.info("No pairs trading opportunity found.")
        return None

def analyze_all_pairs():
    analysis_summary = []
    for ticker1, ticker2 in PREDEFINED_PAIRS:
        correlation = calculate_correlation(ticker1, ticker2, LOOKBACK_DAYS)
        z_score = calculate_spread_zscore(ticker1, ticker2, LOOKBACK_DAYS)
        analysis_summary.append({
            'pair': (ticker1, ticker2),
            'correlation': correlation,
            'zscore': z_score
        })
    return analysis_summary
