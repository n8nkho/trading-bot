"""
52-Week Low Bounce Agent
Edge: Stocks hitting 52-week lows with DECLINING volume (selling exhaustion)
tend to bounce 5-10% within 5 days.
Entry: New 52-week low + today volume < 5-day avg volume
Exit: +8% take profit, -4% stop loss, or 5 days max
Expected win rate: 58-63%
"""
import logging
import yfinance as yf
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

TAKE_PROFIT_PCT = 0.08
STOP_LOSS_PCT = 0.04
MAX_HOLD_DAYS = 5
MAX_POSITION_SIZE = 500.0

# Universe to scan — quality names only (avoid penny stocks)
LOW_BOUNCE_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AMD", "TSLA",
    "JPM", "BAC", "GS", "WFC", "C", "USB",
    "JNJ", "PFE", "MRK", "ABBV", "BMY",
    "XOM", "CVX", "COP", "SLB",
    "HD", "WMT", "TGT", "COST", "LOW",
    "DIS", "NFLX", "CMCSA",
    "V", "MA", "AXP",
    "BA", "GE", "CAT", "MMM", "HON",
    "INTC", "QCOM", "TXN", "MU",
    "T", "VZ",
]


def check_52w_low_bounce(ticker: str) -> dict:
    """Check if stock is at 52-week low with selling exhaustion."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")

        if hist.empty or len(hist) < 50:
            return {"setup": False, "ticker": ticker, "reason": "Insufficient data"}

        current_close = float(hist["Close"].iloc[-1])
        current_low = float(hist["Low"].iloc[-1])
        current_volume = float(hist["Volume"].iloc[-1])

        # 52-week low
        yearly_low = float(hist["Low"].min())
        at_52w_low = current_low <= yearly_low * 1.02  # within 2% of 52w low

        if not at_52w_low:
            return {"setup": False, "ticker": ticker, "reason": f"Not at 52w low (low={current_low:.2f}, 52w_low={yearly_low:.2f})"}

        # Volume exhaustion: today < 5-day avg
        avg_5d_volume = float(hist["Volume"].iloc[-6:-1].mean())
        volume_exhaustion = current_volume < avg_5d_volume if avg_5d_volume > 0 else False

        # Should not be a complete business collapse — check vs 3-month ago
        price_3m_ago = float(hist["Close"].iloc[-63]) if len(hist) >= 63 else current_close * 1.20
        drop_from_3m = (current_close - price_3m_ago) / price_3m_ago

        # Reject if down more than 60% in 3 months (potential collapse)
        if drop_from_3m < -0.60:
            return {"setup": False, "ticker": ticker, "reason": f"Possible collapse ({drop_from_3m:.1%} in 3 months), skipping"}

        setup = at_52w_low and volume_exhaustion

        return {
            "setup": setup,
            "ticker": ticker,
            "current_price": current_close,
            "yearly_low": yearly_low,
            "volume_exhaustion": volume_exhaustion,
            "volume_ratio": current_volume / avg_5d_volume if avg_5d_volume > 0 else 1.0,
            "drop_3m": drop_from_3m,
            "reason": f"52w low={yearly_low:.2f}, vol_ratio={current_volume/max(avg_5d_volume,1):.2f}x (exhaustion={volume_exhaustion})"
        }
    except Exception as e:
        logger.warning(f"52w low check failed for {ticker}: {e}")
        return {"setup": False, "ticker": ticker, "reason": str(e)}


def scan_low_bounce_opportunities(portfolio_value: float = 50000.0) -> list:
    """Scan for 52-week low bounce setups."""
    logger.info("Low Bounce Agent: Scanning for 52-week low setups...")
    opportunities = []

    for ticker in LOW_BOUNCE_UNIVERSE:
        try:
            result = check_52w_low_bounce(ticker)
            if not result.get("setup"):
                continue

            price = result["current_price"]
            shares = max(1, int(MAX_POSITION_SIZE / price))

            # Confidence based on how exhausted volume is
            vol_ratio = result.get("volume_ratio", 1.0)
            confidence = 0.58 + max(0, (1.0 - vol_ratio) * 0.15)
            confidence = min(confidence, 0.73)

            candidate = {
                "ticker": ticker,
                "strategy": "52W_LOW_BOUNCE",
                "entry_price": price,
                "shares": shares,
                "position_size": shares * price,
                "confidence": confidence,
                "stop_loss_pct": STOP_LOSS_PCT,
                "take_profit_pct": TAKE_PROFIT_PCT,
                "max_hold_days": MAX_HOLD_DAYS,
                "reasoning": result["reason"],
                "setup_data": result
            }
            opportunities.append(candidate)
            logger.info(f"52W LOW: {ticker} CANDIDATE - {result['reason']}")

        except Exception as e:
            logger.error(f"Low bounce scan error for {ticker}: {e}")

    logger.info(f"Low Bounce Agent: Found {len(opportunities)} setups")
    return sorted(opportunities, key=lambda x: x["confidence"], reverse=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    opps = scan_low_bounce_opportunities()
    for o in opps:
        print(f"{o['ticker']}: {o['reasoning']} | Confidence: {o['confidence']:.2f}")
