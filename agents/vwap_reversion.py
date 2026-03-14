from __future__ import annotations

"""
VWAP Mean Reversion (Institutional)

Intraday strategy that looks for quality large-cap names that:
- Trade down to (or slightly below) intraday VWAP
- Show a bounce on the next 5-minute candle

Implementation notes:
- Uses Alpaca minute bars via existing orchestrator client if available,
  otherwise falls back to yfinance 5-minute data for demonstration purposes.
- Emits signals only; no direct order placement.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Dict, List

import yfinance as yf

from config.universe_tickers import get_sp500_tickers


logging.basicConfig(
    filename="logs/vwap.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


MIN_MARKET_CAP = 10_000_000_000  # $10B
MIN_AVG_VOLUME = 2_000_000


@dataclass
class VwapCandidate:
    ticker: str
    current_price: float
    confidence: float
    reasoning: str

    def to_orchestrator_candidate(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "current_price": self.current_price,
            "analysis": {
                "confidence": self.confidence,
                "reasoning": self.reasoning,
                "score": None,
            },
            "strategy_id": "vwap_reversion",
        }


def _compute_vwap(close, volume) -> float:
    num = (close * volume).sum()
    den = volume.sum()
    return float(num / den) if den else 0.0


def _evaluate_vwap_candidate(ticker: str, now_et: datetime) -> VwapCandidate | None:
    """
    Use 5-minute intraday bars from yfinance as a proxy for VWAP scans.
    """
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        logger.debug(f"{ticker}: failed to load info: {e}")
        return None

    if not info:
        return None

    mcap = float(info.get("marketCap") or 0)
    avg_vol = float(info.get("averageVolume") or 0)
    if mcap < MIN_MARKET_CAP or avg_vol < MIN_AVG_VOLUME:
        return None

    # yfinance 5-minute intraday data for today
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="5m")
    except Exception as e:
        logger.debug(f"{ticker}: failed to load intraday history: {e}")
        return None

    if hist is None or hist.empty or len(hist) < 5:
        return None

    hist = hist.sort_index()
    close = hist["Close"]
    vol = hist["Volume"]
    vwap = _compute_vwap(close, vol)
    if vwap <= 0:
        return None

    last = hist.iloc[-1]
    prev = hist.iloc[-2]
    last_close = float(last["Close"])
    prev_close = float(prev["Close"])

    # Require that price recently touched or dipped slightly below VWAP,
    # then bounced at least 0.5% on the latest bar.
    touch_pct = (last_close - vwap) / vwap * 100.0
    bounce_pct = (last_close - prev_close) / prev_close * 100.0 if prev_close > 0 else 0.0

    if not (-0.5 <= touch_pct <= 1.0 and bounce_pct >= 0.5):
        return None

    confidence = min(0.8, 0.6 + 0.5 * (bounce_pct / 3.0))
    reasoning = (
        f"VWAP reversion: price near VWAP (delta {touch_pct:.2f}%), "
        f"latest 5m candle bounce {bounce_pct:.2f}%"
    )

    return VwapCandidate(
        ticker=ticker,
        current_price=last_close,
        confidence=confidence,
        reasoning=reasoning,
    )


def vwap_reversion_strategy(portfolio_value: float = 10_000.0) -> List[Dict[str, Any]]:
    """
    Main entry for VWAP mean-reversion strategy.

    Intended to be run every 5 minutes between 10:00 and 15:00 ET.
    """
    logger.info("=" * 80)
    logger.info("VWAP REVERSION STRATEGY - SCAN START")
    logger.info("=" * 80)

    # Approximate US/Eastern by assuming server clock is UTC +/- offset; for now,
    # we just use local time window 10:00-15:00 as configured in cron.
    now_local = datetime.now()
    now_t = now_local.time()
    if not (time(10, 0) <= now_t <= time(15, 0)):
        logger.info("VWAP REVERSION: outside configured intraday window; skipping")
        return []

    universe = get_sp500_tickers()
    logger.info(f"Scanning {len(universe)} large-cap tickers for VWAP reversion setups")

    candidates: List[VwapCandidate] = []
    for sym in universe:
        try:
            c = _evaluate_vwap_candidate(sym, now_local)
            if c:
                candidates.append(c)
                logger.info(f"{sym}: VWAP candidate ({c.reasoning})")
        except Exception as e:
            logger.error(f"{sym}: error evaluating VWAP candidate: {e}")
            continue

    logger.info(f"VWAP REVERSION: emitting {len(candidates)} candidates")
    result = [c.to_orchestrator_candidate() for c in candidates]
    logger.info("=" * 80)
    return result


if __name__ == "__main__":
    out = vwap_reversion_strategy()
    print(f"VWAP candidates: {len(out)}")

