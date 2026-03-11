"""
Bear Playbook Agent
Activates in BEAR_TREND and CRISIS regimes.
Trades 1x inverse ETFs for downside exposure (safer than 3x for paper trading).
"""
import logging
import yfinance as yf
from datetime import datetime

logger = logging.getLogger(__name__)

INVERSE_ETFS = {
    "Technology": "PSQ",
    "Financials":  "SEF",
    "Energy":      "DDG",
    "Healthcare":  "RXD",
    "Broad":       "SH",
    "Consumer":    "SZK",
}

SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials":  "XLF",
    "Energy":      "XLE",
    "Healthcare":  "XLV",
    "Consumer":    "XLP",
    "Broad":       "SPY",
}

MAX_POSITION_SIZE = 500.0
TAKE_PROFIT_PCT = 0.05
STOP_LOSS_PCT = 0.03


def find_weakest_sector():
    """Find which sector has the worst 5-day return."""
    try:
        worst_sector = "Broad"
        worst_return = 0.0
        for sector, etf in SECTOR_ETFS.items():
            hist = yf.Ticker(etf).history(period="7d")
            if len(hist) < 3:
                continue
            ret = (float(hist["Close"].iloc[-1]) - float(hist["Close"].iloc[0])) / float(hist["Close"].iloc[0])
            if ret < worst_return:
                worst_return = ret
                worst_sector = sector
        logger.info(f"Weakest sector: {worst_sector} ({worst_return:.1%})")
        return worst_sector
    except Exception as e:
        logger.warning(f"Sector scan failed: {e}")
        return "Broad"


def scan_bear_opportunities(portfolio_value=50000.0):
    """Return inverse ETF trade candidates for bear/crisis regime."""
    logger.info("Bear Playbook: Scanning for downside opportunities...")
    opportunities = []
    try:
        weakest = find_weakest_sector()
        etf_ticker = INVERSE_ETFS.get(weakest, "SH")
        hist = yf.Ticker(etf_ticker).history(period="5d")
        if hist.empty:
            return []
        price = float(hist["Close"].iloc[-1])
        shares = max(1, int(MAX_POSITION_SIZE / price))
        opportunities.append({
            "ticker": etf_ticker,
            "strategy": "BEAR_PLAYBOOK",
            "entry_price": price,
            "shares": shares,
            "position_size": shares * price,
            "confidence": 0.65,
            "stop_loss_pct": STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "reasoning": f"Bear regime: short {weakest} sector via {etf_ticker}",
            "regime_trade": True,
        })
        logger.info(f"Bear Playbook: {etf_ticker} candidate (sector: {weakest})")
    except Exception as e:
        logger.error(f"Bear playbook scan error: {e}")
    return opportunities
