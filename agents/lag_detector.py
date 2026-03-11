"""
Lag Detector - Supply Chain Contagion Trading
When a large-cap leader moves significantly, related supply chain
names tend to lag 12-72 hours. Front-runs the contagion.
"""
import logging
import yfinance as yf
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_POSITION_SIZE = 500.0
TAKE_PROFIT_PCT = 0.06
STOP_LOSS_PCT = 0.03
ANCHOR_MOVE_THRESHOLD = 0.04

SUPPLY_CHAIN_GRAPH = {
    "AAPL":  ["QCOM", "AVGO", "SWKS", "CRUS", "AMAT"],
    "TSLA":  ["ALB", "SQM", "MP"],
    "NVDA":  ["AMAT", "LRCX", "KLAC", "MU"],
    "AMZN":  ["UPS", "FDX", "EXPD"],
    "META":  ["SNAP", "PINS", "TTD"],
    "MSFT":  ["CRM", "NOW", "WDAY"],
    "GS":    ["MS", "JPM", "BAC"],
    "XOM":   ["CVX", "COP", "SLB", "HAL"],
    "BA":    ["HEI", "TDG", "SPR"],
    "COST":  ["WMT", "TGT", "KR"],
}


def check_lag_setup(anchor, dependents):
    """Check if anchor moved but dependents have not yet reacted."""
    results = []
    try:
        anchor_hist = yf.Ticker(anchor).history(period="3d")
        if len(anchor_hist) < 2:
            return []
        anchor_return = (float(anchor_hist["Close"].iloc[-1]) - float(anchor_hist["Close"].iloc[-2])) / float(anchor_hist["Close"].iloc[-2])
        if abs(anchor_return) < ANCHOR_MOVE_THRESHOLD:
            return []
        direction = "down" if anchor_return < 0 else "up"
        logger.info(f"LAG: {anchor} moved {anchor_return:.1%} ({direction})")
        for dep in dependents:
            try:
                dep_hist = yf.Ticker(dep).history(period="3d")
                if len(dep_hist) < 2:
                    continue
                dep_return = (float(dep_hist["Close"].iloc[-1]) - float(dep_hist["Close"].iloc[-2])) / float(dep_hist["Close"].iloc[-2])
                dep_price = float(dep_hist["Close"].iloc[-1])
                lag_confirmed = (direction == "down" and dep_return > -0.01) or (direction == "up" and dep_return < 0.01)
                if lag_confirmed and dep_price > 1.0:
                    shares = max(1, int(MAX_POSITION_SIZE / dep_price))
                    results.append({
                        "ticker": dep,
                        "strategy": "LAG_DETECTOR",
                        "entry_price": dep_price,
                        "shares": shares,
                        "position_size": shares * dep_price,
                        "confidence": 0.63 + min(abs(anchor_return) * 0.5, 0.10),
                        "stop_loss_pct": STOP_LOSS_PCT,
                        "take_profit_pct": TAKE_PROFIT_PCT,
                        "lag_direction": direction,
                        "anchor": anchor,
                        "anchor_move": anchor_return,
                        "reasoning": f"{anchor} moved {anchor_return:.1%}, {dep} not yet priced in ({dep_return:.1%})",
                    })
            except Exception as e:
                logger.warning(f"Lag check failed for dependent {dep}: {e}")
    except Exception as e:
        logger.error(f"Lag check failed for anchor {anchor}: {e}")
    return results


def scan_lag_opportunities(portfolio_value=50000.0):
    """Scan all supply chain relationships for lag setups."""
    logger.info("Lag Detector: Scanning supply chain relationships...")
    all_opportunities = []
    for anchor, dependents in SUPPLY_CHAIN_GRAPH.items():
        try:
            results = check_lag_setup(anchor, dependents)
            all_opportunities.extend(results)
        except Exception as e:
            logger.error(f"Lag scan error for {anchor}: {e}")
    logger.info(f"Lag Detector: Found {len(all_opportunities)} lag opportunities")
    return sorted(all_opportunities, key=lambda x: x["confidence"], reverse=True)
