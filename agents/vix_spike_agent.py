"""
VIX Spike Reversal Agent
Edge: When VIX spikes >20% in a single day, SPY/QQQ tend to bounce 1-3% within 3 days.
Historically very reliable (70%+ win rate).
Entry: VIX 1-day change > 20%, buy SPY at close
Exit: 3 days or +2.5% take profit or -1.5% stop loss
"""
import logging
import yfinance as yf
from datetime import datetime

logger = logging.getLogger(__name__)

VIX_SPIKE_PCT = 0.20       # 20% single-day VIX spike triggers entry
TAKE_PROFIT_PCT = 0.025    # 2.5%
STOP_LOSS_PCT = 0.015      # 1.5%
MAX_HOLD_DAYS = 3
POSITION_SIZE = 500.0


def check_vix_spike() -> dict:
    """Check if VIX has spiked significantly today."""
    try:
        vix = yf.Ticker("^VIX").history(period="5d")
        if vix.empty or len(vix) < 2:
            return {"spike": False, "reason": "Could not fetch VIX data"}

        vix_today = float(vix["Close"].iloc[-1])
        vix_yesterday = float(vix["Close"].iloc[-2])
        vix_change = (vix_today - vix_yesterday) / vix_yesterday

        spike = vix_change >= VIX_SPIKE_PCT and vix_today >= 20.0

        return {
            "spike": spike,
            "vix_today": vix_today,
            "vix_yesterday": vix_yesterday,
            "vix_change_pct": vix_change,
            "reason": f"VIX: {vix_yesterday:.1f} → {vix_today:.1f} ({vix_change:+.1%})"
        }
    except Exception as e:
        logger.warning(f"VIX spike check failed: {e}")
        return {"spike": False, "reason": str(e)}


def scan_vix_spike_opportunities(portfolio_value: float = 50000.0) -> list:
    """Check for VIX spike reversal entry on SPY/QQQ."""
    logger.info("VIX Spike Agent: Checking for spike reversal setups...")

    result = check_vix_spike()
    if not result.get("spike"):
        logger.info(f"VIX Spike Agent: No spike detected. {result.get('reason', '')}")
        return []

    opportunities = []
    for etf in ["SPY", "QQQ"]:
        try:
            hist = yf.Ticker(etf).history(period="2d")
            if hist.empty:
                continue
            price = float(hist["Close"].iloc[-1])
            shares = max(1, int(POSITION_SIZE / price))

            candidate = {
                "ticker": etf,
                "strategy": "VIX_SPIKE_REVERSAL",
                "entry_price": price,
                "shares": shares,
                "position_size": shares * price,
                "confidence": 0.70,
                "stop_loss_pct": STOP_LOSS_PCT,
                "take_profit_pct": TAKE_PROFIT_PCT,
                "max_hold_days": MAX_HOLD_DAYS,
                "reasoning": result["reason"],
                "vix_data": result
            }
            opportunities.append(candidate)
            logger.info(f"VIX SPIKE: {etf} reversal candidate - {result['reason']}")
        except Exception as e:
            logger.error(f"VIX spike scan error for {etf}: {e}")

    return opportunities


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    opps = scan_vix_spike_opportunities()
    for o in opps:
        print(f"{o['ticker']}: {o['reasoning']} | Confidence: {o['confidence']:.2f}")
