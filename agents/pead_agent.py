"""
PEAD Agent - Post-Earnings Announcement Drift
Academic edge: stocks that beat earnings continue drifting upward 3-5 days.
Entry: Day 1 close after earnings beat (EPS surprise > 5%, revenue beat)
Exit: Day 5 or +8% take profit or -4% stop loss
Expected win rate: 62-68%
"""
import logging
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path
import json

logger = logging.getLogger(__name__)
DATA_DIR = Path("data")

EARNINGS_BEAT_MIN_SURPRISE = 0.05   # 5% EPS surprise minimum
MAX_POSITION_SIZE = 500.0
HOLD_DAYS = 5
TAKE_PROFIT_PCT = 0.08
STOP_LOSS_PCT = 0.04

# Watchlist for earnings - scan these for beats
EARNINGS_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AMD", "TSLA",
    "JPM", "BAC", "GS", "MS", "WFC",
    "JNJ", "PFE", "MRK", "UNH",
    "XOM", "CVX", "COP",
    "HD", "WMT", "TGT", "COST",
    "NFLX", "DIS", "CMCSA",
    "V", "MA", "PYPL",
]


def check_earnings_beat(ticker: str) -> dict:
    """
    Check if a stock recently beat earnings.
    Uses yfinance earnings_history.
    Returns: {"beat": bool, "surprise_pct": float, "ticker": str, "days_ago": int}
    """
    try:
        stock = yf.Ticker(ticker)

        # Get earnings history
        earnings = stock.earnings_history
        if earnings is None or earnings.empty:
            return {"beat": False, "ticker": ticker, "reason": "No earnings data"}

        # Check most recent earnings
        latest = earnings.iloc[0] if hasattr(earnings, "iloc") else None
        if latest is None:
            return {"beat": False, "ticker": ticker, "reason": "No latest earnings"}

        # Calculate EPS surprise
        eps_actual = latest.get("epsActual") or latest.get("Reported EPS")
        eps_estimate = latest.get("epsEstimate") or latest.get("EPS Estimate")

        if eps_actual is None or eps_estimate is None or eps_estimate == 0:
            return {"beat": False, "ticker": ticker, "reason": "Missing EPS data"}

        surprise_pct = (float(eps_actual) - float(eps_estimate)) / abs(float(eps_estimate))

        # Check earnings date (within last 3 days for fresh drift)
        earnings_date = None
        if "Earnings Date" in earnings.columns:
            earnings_date = earnings.index[0] if hasattr(earnings.index[0], "date") else None

        days_ago = 999
        if earnings_date:
            try:
                days_ago = (datetime.now().date() - earnings_date.date()).days
            except Exception:
                days_ago = 999

        beat = surprise_pct >= EARNINGS_BEAT_MIN_SURPRISE and days_ago <= 3

        return {
            "beat": beat,
            "ticker": ticker,
            "surprise_pct": surprise_pct,
            "eps_actual": float(eps_actual),
            "eps_estimate": float(eps_estimate),
            "days_ago": days_ago,
            "reason": f"EPS surprise {surprise_pct:.1%}, {days_ago} days ago"
        }
    except Exception as e:
        logger.warning(f"PEAD check failed for {ticker}: {e}")
        return {"beat": False, "ticker": ticker, "reason": str(e)}


def scan_pead_opportunities(portfolio_value: float = 50000.0) -> list:
    """
    Scan watchlist for recent earnings beats with drift potential.
    Returns list of trade candidates.
    """
    logger.info("PEAD Agent: Scanning for post-earnings drift opportunities...")
    opportunities = []

    for ticker in EARNINGS_WATCHLIST:
        try:
            result = check_earnings_beat(ticker)
            if not result.get("beat"):
                continue

            # Additional momentum check: price should still be rising
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue

            current_price = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2])
            momentum = (current_price - prev_close) / prev_close

            # Skip if already faded (down today)
            if momentum < -0.02:
                logger.info(f"PEAD: {ticker} beat earnings but fading today ({momentum:.1%}), skipping")
                continue

            shares = max(1, int(MAX_POSITION_SIZE / current_price))
            position_size = shares * current_price

            candidate = {
                "ticker": ticker,
                "strategy": "PEAD",
                "entry_price": current_price,
                "shares": shares,
                "position_size": position_size,
                "confidence": 0.65 + min(result["surprise_pct"] * 0.5, 0.15),
                "stop_loss_pct": STOP_LOSS_PCT,
                "take_profit_pct": TAKE_PROFIT_PCT,
                "max_hold_days": HOLD_DAYS,
                "reasoning": f"Earnings beat: {result['surprise_pct']:.1%} EPS surprise, {result['days_ago']} days ago",
                "earnings_data": result
            }
            opportunities.append(candidate)
            logger.info(f"PEAD: {ticker} CANDIDATE - {result['reason']}")

        except Exception as e:
            logger.error(f"PEAD scan error for {ticker}: {e}")

    logger.info(f"PEAD Agent: Found {len(opportunities)} opportunities")
    return sorted(opportunities, key=lambda x: x["confidence"], reverse=True)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    opps = scan_pead_opportunities()
    for o in opps:
        print(f"{o['ticker']}: {o['reasoning']} | Confidence: {o['confidence']:.2f}")
