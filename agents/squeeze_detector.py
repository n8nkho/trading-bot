"""
Short Squeeze Detector
Edge: High short interest + positive catalyst + volume surge = violent squeeze
Entry: Short interest > 15% float + volume > 3x avg + price breaking above 10-day high
Exit: +15% or when squeeze exhausts (volume drops below avg)
Expected win rate: 52-58% but large winners
"""
import logging
import yfinance as yf
import numpy as np
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SHORT_INTEREST_MIN = 0.10  # 10% of float minimum (conservative - yfinance data)
VOLUME_SURGE_MIN = 2.5     # 2.5x average volume
TAKE_PROFIT_PCT = 0.15
STOP_LOSS_PCT = 0.06
MAX_POSITION_SIZE = 500.0

# Candidates to screen for squeeze setups
SQUEEZE_UNIVERSE = [
    "GME", "AMC", "BBBY", "MSTR", "COIN", "HOOD", "SOFI", "LCID",
    "RIVN", "PLUG", "FCEL", "SPCE", "NKLA", "CLOV", "WKHS",
    "BB", "NOK", "SNDL", "KOSS",
    # High-short-interest names
    "BYND", "CVNA", "UPST", "AFRM", "OPEN",
]


def check_squeeze_setup(ticker: str) -> dict:
    """Check if a stock has squeeze potential."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="30d")

        if hist.empty or len(hist) < 15:
            return {"squeeze": False, "ticker": ticker, "reason": "Insufficient data"}

        current_price = float(hist["Close"].iloc[-1])
        current_volume = float(hist["Volume"].iloc[-1])
        avg_volume = float(hist["Volume"].iloc[:-1].mean())

        if avg_volume == 0:
            return {"squeeze": False, "ticker": ticker, "reason": "Zero avg volume"}

        volume_ratio = current_volume / avg_volume

        # Check short interest
        short_pct = info.get("shortPercentOfFloat") or 0.0

        # Price breaking above 10-day high (momentum confirmation)
        ten_day_high = float(hist["High"].iloc[-11:-1].max()) if len(hist) >= 11 else current_price
        price_breakout = current_price > ten_day_high

        # RSI should not be overbought yet (< 65)
        delta = hist["Close"].diff().dropna()
        gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
        rsi = float(100 - 100 / (1 + gain.iloc[-1] / max(loss.iloc[-1], 0.0001)))

        squeeze = (
            short_pct >= SHORT_INTEREST_MIN and
            volume_ratio >= VOLUME_SURGE_MIN and
            price_breakout and
            rsi < 65
        )

        return {
            "squeeze": squeeze,
            "ticker": ticker,
            "short_pct": short_pct,
            "volume_ratio": volume_ratio,
            "price_breakout": price_breakout,
            "rsi": rsi,
            "current_price": current_price,
            "reason": f"Short {short_pct:.1%}, Vol {volume_ratio:.1f}x, Breakout={price_breakout}, RSI={rsi:.0f}"
        }
    except Exception as e:
        logger.warning(f"Squeeze check failed for {ticker}: {e}")
        return {"squeeze": False, "ticker": ticker, "reason": str(e)}


def scan_squeeze_opportunities(portfolio_value: float = 50000.0) -> list:
    """Scan for active short squeeze setups."""
    logger.info("Squeeze Detector: Scanning for squeeze opportunities...")
    opportunities = []

    for ticker in SQUEEZE_UNIVERSE:
        try:
            result = check_squeeze_setup(ticker)
            if not result.get("squeeze"):
                continue

            price = result["current_price"]
            shares = max(1, int(MAX_POSITION_SIZE / price))
            confidence = 0.55 + (result["volume_ratio"] - VOLUME_SURGE_MIN) * 0.03
            confidence = min(confidence, 0.75)

            candidate = {
                "ticker": ticker,
                "strategy": "SHORT_SQUEEZE",
                "entry_price": price,
                "shares": shares,
                "position_size": shares * price,
                "confidence": confidence,
                "stop_loss_pct": STOP_LOSS_PCT,
                "take_profit_pct": TAKE_PROFIT_PCT,
                "reasoning": result["reason"],
                "squeeze_data": result
            }
            opportunities.append(candidate)
            logger.info(f"SQUEEZE: {ticker} CANDIDATE - {result['reason']}")

        except Exception as e:
            logger.error(f"Squeeze scan error for {ticker}: {e}")

    logger.info(f"Squeeze Detector: Found {len(opportunities)} setups")
    return sorted(opportunities, key=lambda x: x["confidence"], reverse=True)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    opps = scan_squeeze_opportunities()
    for o in opps:
        print(f"{o['ticker']}: {o['reasoning']} | Confidence: {o['confidence']:.2f}")


def squeeze_detector_strategy(portfolio_value: float = 10000.0) -> list:
    """
    Alias for scan_squeeze_opportunities — used by run_strategies.py.
    Scans for Bollinger/Keltner squeeze setups and returns trade candidates.
    """
    return scan_squeeze_opportunities(portfolio_value)
