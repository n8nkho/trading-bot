"""
ETF Rebalance Frontrunner
Month-end markup window (last 3 days) and Russell season (May-June).
Favors large-cap longs with positive momentum during these windows.
"""
import logging
import yfinance as yf
from datetime import date
import calendar as cal

logger = logging.getLogger(__name__)

MAX_POSITION_SIZE = 500.0
TAKE_PROFIT_PCT = 0.05
STOP_LOSS_PCT = 0.025

LARGE_CAPS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "UNH"]
RUSSELL_SEASON_MONTHS = [5, 6]


def is_month_end_window():
    """True if within last 3 calendar days of month."""
    today = date.today()
    last_day = cal.monthrange(today.year, today.month)[1]
    return today.day >= last_day - 3


def is_russell_season():
    """True if in Russell reconstitution season (May-June)."""
    return date.today().month in RUSSELL_SEASON_MONTHS


def scan_etf_rebalance_opportunities(portfolio_value=50000.0):
    """During rebalancing windows, favor large-cap momentum longs."""
    logger.info("ETF Rebalance Agent: Checking windows...")
    month_end = is_month_end_window()
    russell = is_russell_season()

    if not month_end and not russell:
        logger.info("ETF Rebalance: No active window")
        return []

    reason_prefix = "Month-end markup" if month_end else "Russell season momentum"
    opportunities = []

    for ticker in LARGE_CAPS:
        try:
            hist = yf.Ticker(ticker).history(period="10d")
            if len(hist) < 5:
                continue
            price = float(hist["Close"].iloc[-1])
            ret_5d = (price - float(hist["Close"].iloc[-5])) / float(hist["Close"].iloc[-5])
            if ret_5d < 0.005:
                continue
            shares = max(1, int(MAX_POSITION_SIZE / price))
            confidence = min(0.60 + ret_5d * 2, 0.72)
            opportunities.append({
                "ticker": ticker,
                "strategy": "ETF_REBALANCE",
                "entry_price": price,
                "shares": shares,
                "position_size": shares * price,
                "confidence": confidence,
                "stop_loss_pct": STOP_LOSS_PCT,
                "take_profit_pct": TAKE_PROFIT_PCT,
                "reasoning": f"{reason_prefix}: {ticker} +{ret_5d:.1%} 5d",
            })
        except Exception as e:
            logger.error(f"ETF rebalance scan error for {ticker}: {e}")

    return sorted(opportunities, key=lambda x: x["confidence"], reverse=True)
