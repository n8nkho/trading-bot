"""
Institutional Footprint Detector
High late-day volume + small price move = institutional absorption.
Next-day signal: price follows direction of absorption.
Only active 2-4 PM ET (last 2 hours of trading day).
"""
import logging
import yfinance as yf
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
ET = pytz.timezone("US/Eastern")

MAX_POSITION_SIZE = 500.0
TAKE_PROFIT_PCT = 0.04
STOP_LOSS_PCT = 0.025

ACCUMULATION_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "JPM", "GS", "MS", "V", "MA",
    "SPY", "QQQ", "IWM",
]


def check_accumulation(ticker):
    """Detect institutional accumulation via 5-min intraday bars."""
    try:
        intraday = yf.Ticker(ticker).history(period="1d", interval="5m")
        if intraday.empty or len(intraday) < 12:
            return {"accumulation": False, "ticker": ticker, "reason": "Insufficient intraday data"}

        total_vol = float(intraday["Volume"].sum())
        if total_vol == 0:
            return {"accumulation": False, "ticker": ticker, "reason": "Zero volume"}

        last_6 = intraday.tail(6)
        last_30min_vol = float(last_6["Volume"].sum())
        vol_concentration = last_30min_vol / total_vol

        last_price = float(last_6["Close"].iloc[-1])
        first_price = float(last_6["Close"].iloc[0])
        avg_price = float(last_6["Close"].mean())
        price_impact = abs(last_price - first_price) / max(avg_price, 0.01)

        # VWAP
        vwap = float((intraday["Close"] * intraday["Volume"]).sum() / max(intraday["Volume"].sum(), 1))
        bullish = last_price > vwap

        accumulation = vol_concentration > 0.28 and price_impact < 0.006 and bullish

        return {
            "accumulation": accumulation,
            "ticker": ticker,
            "vol_concentration": vol_concentration,
            "price_impact": price_impact,
            "vwap": vwap,
            "current_price": last_price,
            "bullish": bullish,
            "reason": f"Vol_conc={vol_concentration:.1%}, price_impact={price_impact:.3%}, vwap_bullish={bullish}",
        }
    except Exception as e:
        logger.warning(f"Accumulation check failed for {ticker}: {e}")
        return {"accumulation": False, "ticker": ticker, "reason": str(e)}


def scan_institutional_footprints(portfolio_value=50000.0):
    """Scan for institutional accumulation. Only runs 2-4 PM ET."""
    now_et = datetime.now(ET)
    if not (14 <= now_et.hour <= 16):
        logger.info("Institutional Detector: Outside 2-4 PM ET window")
        return []

    logger.info("Institutional Detector: Scanning for accumulation...")
    opportunities = []

    for ticker in ACCUMULATION_UNIVERSE:
        try:
            result = check_accumulation(ticker)
            if not result.get("accumulation"):
                continue
            price = result["current_price"]
            shares = max(1, int(MAX_POSITION_SIZE / price))
            confidence = min(0.62 + result["vol_concentration"] * 0.1, 0.75)
            opportunities.append({
                "ticker": ticker,
                "strategy": "INSTITUTIONAL_FOOTPRINT",
                "entry_price": price,
                "shares": shares,
                "position_size": shares * price,
                "confidence": confidence,
                "stop_loss_pct": STOP_LOSS_PCT,
                "take_profit_pct": TAKE_PROFIT_PCT,
                "reasoning": result["reason"],
                "setup_data": result,
            })
            logger.info(f"INSTITUTIONAL: {ticker} - {result['reason']}")
        except Exception as e:
            logger.error(f"Institutional scan error for {ticker}: {e}")

    return sorted(opportunities, key=lambda x: x["confidence"], reverse=True)
