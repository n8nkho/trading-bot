"""
Pre-Mortem Risk Check - Monte Carlo worst-case simulation.
Blocks entries where 5th-percentile 5-day path implies >8% loss.
"""
import logging
import numpy as np
import yfinance as yf
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_ACCEPTABLE_TAIL_LOSS = -0.08
SIMULATION_PATHS = 500
HORIZON_DAYS = 5


def run_premortem(ticker, entry_price, shares, lookback_days=90):
    """
    Simulate 500 random price paths over 5 days.
    Returns dict with approved bool and risk metrics.
    """
    try:
        hist = yf.Ticker(ticker).history(period=f"{lookback_days}d")
        if hist.empty or len(hist) < 20:
            return {
                "approved": True,
                "reason": "Insufficient data for simulation - allowing",
                "worst_5pct_loss": 0.0,
                "probability_profit": 0.65,
                "median_outcome": entry_price,
            }

        daily_returns = hist["Close"].pct_change().dropna()
        mu = float(daily_returns.mean())
        sigma = float(daily_returns.std())
        if sigma == 0:
            sigma = 0.02

        rng = np.random.default_rng()
        paths = rng.normal(mu, sigma, size=(SIMULATION_PATHS, HORIZON_DAYS))
        cumulative = (1 + paths).cumprod(axis=1)
        final_prices = entry_price * cumulative[:, -1]

        worst_5pct_price = float(np.percentile(final_prices, 5))
        worst_5pct_loss = (worst_5pct_price - entry_price) / entry_price
        prob_profit = float(np.sum(final_prices > entry_price)) / SIMULATION_PATHS
        median_outcome = float(np.median(final_prices))

        approved = worst_5pct_loss > MAX_ACCEPTABLE_TAIL_LOSS
        reason = (
            f"Pre-mortem: 5th_pct_loss={worst_5pct_loss:.1%}, "
            f"prob_profit={prob_profit:.0%}, median={median_outcome:.2f}"
        )

        if not approved:
            logger.warning(f"PRE-MORTEM BLOCK {ticker}: tail loss {worst_5pct_loss:.1%}")
        else:
            logger.info(f"PRE-MORTEM OK {ticker}: {reason}")

        return {
            "approved": approved,
            "worst_5pct_loss": worst_5pct_loss,
            "probability_profit": prob_profit,
            "median_outcome": median_outcome,
            "reason": reason,
        }

    except Exception as e:
        logger.warning(f"Pre-mortem simulation failed for {ticker}: {e} - allowing")
        return {
            "approved": True,
            "reason": f"Simulation error (allowing): {e}",
            "worst_5pct_loss": 0.0,
            "probability_profit": 0.65,
            "median_outcome": entry_price,
        }
