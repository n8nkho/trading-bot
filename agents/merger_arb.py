import requests
import yfinance as yf
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(filename='logs/merger_arb.log', level=logging.INFO)

ACTIVE_MERGERS = [
    # Format: (target, acquirer, offer_price, expected_close_date)
    # User will manually add deals as they're announced
    # Example: ('ATVI', 'MSFT', 95.00, '2024-10-13')
]

def calculate_merger_spread(target_ticker, offer_price):
    """
    Calculate the merger spread based on the offer price and current target price.
    
    Args:
        target_ticker (str): The ticker of the target company.
        offer_price (float): The offer price for the target company.
    
    Returns:
        float: Spread percentage
    """
    stock = yf.Ticker(target_ticker)
    current_price = stock.history(period="1d")['Close'].iloc[-1]
    spread = ((offer_price - current_price) / current_price) * 100
    logging.info(f"Calculated spread for {target_ticker}: {spread:.2f}%")
    return spread

def calculate_annualized_return(spread_pct, days_to_close):
    """
    Calculate the annualized return based on the spread percentage and days to close.
    
    Args:
        spread_pct (float): The spread percentage.
        days_to_close (int): The number of days until the expected close date.
    
    Returns:
        float: Annualized return percentage
    """
    annualized_return = (spread_pct / days_to_close) * 365
    logging.info(f"Calculated annualized return: {annualized_return:.2f}%")
    return annualized_return

def assess_deal_quality(spread_pct, days_to_close):
    """
    Assess the quality of a merger deal.
    
    Args:
        spread_pct (float): The spread percentage.
        days_to_close (int): The number of days until the expected close date.
    
    Returns:
        str: Deal quality ('GREAT', 'GOOD', 'POOR')
    """
    if spread_pct > 5 and days_to_close < 120:
        quality = "GREAT"
    elif spread_pct > 3 and days_to_close < 180:
        quality = "GOOD"
    else:
        quality = "POOR"
    logging.info(f"Assessed deal quality: {quality}")
    return quality

def merger_arb_entry(target, acquirer, offer_price, close_date, portfolio_value):
    """
    Recommend entry for a merger arbitrage opportunity.
    
    Args:
        target (str): The target company.
        acquirer (str): The acquiring company.
        offer_price (float): The offer price for the target company.
        close_date (str): The expected close date in 'YYYY-MM-DD' format.
        portfolio_value (float): The total value of the portfolio.
    
    Returns:
        dict: Trade recommendation
    """
    spread_pct = calculate_merger_spread(target, offer_price)
    days_to_close = (datetime.strptime(close_date, '%Y-%m-%d') - datetime.now()).days
    annualized_return = calculate_annualized_return(spread_pct, days_to_close)
    quality = assess_deal_quality(spread_pct, days_to_close)
    
    if quality in ["GREAT", "GOOD"]:
        position_size = portfolio_value * 0.15
        recommendation = {
            'target': target,
            'acquirer': acquirer,
            'offer_price': offer_price,
            'spread_pct': spread_pct,
            'annualized_return': annualized_return,
            'quality': quality,
            'position_size': position_size,
            'exit_spread': 1.0
        }
        logging.info(f"Trade recommendation: {recommendation}")
        return recommendation
    else:
        logging.info(f"No trade recommendation for {target}. Deal quality: {quality}")
        return None

def merger_arb_strategy(portfolio_value):
    """
    Implement the merger arbitrage strategy by finding active mergers with favorable conditions.
    
    Args:
        portfolio_value (float): The total value of the portfolio.
    
    Returns:
        list: Trade recommendations.
    """
    recommendations = []
    for deal in ACTIVE_MERGERS:
        target, acquirer, offer_price, close_date = deal
        recommendation = merger_arb_entry(target, acquirer, offer_price, close_date, portfolio_value)
        if recommendation:
            recommendations.append(recommendation)
    logging.info(f"Total recommendations: {len(recommendations)}")
    return recommendations

def add_merger_deal(target, acquirer, offer_price, close_date):
    """
    Add a new merger deal to the active mergers list.
    
    Args:
        target (str): The target company.
        acquirer (str): The acquiring company.
        offer_price (float): The offer price for the target company.
        close_date (str): The expected close date in 'YYYY-MM-DD' format.
    """
    try:
        datetime.strptime(close_date, '%Y-%m-%d')
        ACTIVE_MERGERS.append((target, acquirer, offer_price, close_date))
        logging.info(f"Added new merger deal: {target} acquired by {acquirer} at {offer_price}, closing on {close_date}")
    except ValueError:
        logging.error("Invalid date format for close_date. Use 'YYYY-MM-DD'.")
