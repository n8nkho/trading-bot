from __future__ import annotations

"""
Insider Buying Tracker

NOTE: Full SEC Form 4 parsing is non-trivial and requires robust rate-limited
integration with EDGAR. This agent currently focuses on the *stock-quality and
technical side* of the strategy and treats insider data as unavailable by
default. When EDGAR integration is configured, the placeholder hooks can be
extended to feed real insider clusters.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

import yfinance as yf

from agents.screener_agent import get_sp500_tickers


logging.basicConfig(
    filename="logs/insider.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


MIN_MARKET_CAP = 1_000_000_000  # $1B
MIN_AVG_VOLUME = 1_000_000


@dataclass
class InsiderCandidate:
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
            "strategy_id": "insider_tracker",
        }


def _placeholder_insider_screen() -> List[str]:
    """
    Placeholder for future SEC Form 4 parsing.

    Returns a curated, very small set of tickers that *could* be interesting
    from an insider perspective once real data is wired in. For now, this
    simply logs that insider data is unavailable.
    """
    logger.info(
        "INSIDER TRACKER: EDGAR / Form 4 integration not configured; "
        "running in technical-only mode with no real insider signals."
    )
    return []


def insider_buying_strategy(portfolio_value: float = 10_000.0) -> List[Dict[str, Any]]:
    """
    Main entry point for the Insider Buying Tracker.

    Currently operates in "safe" mode: if no insider data source is configured,
    it returns an empty candidate list while logging the limitation.
    """
    logger.info("=" * 80)
    logger.info("INSIDER BUYING STRATEGY - SCAN START")
    logger.info("=" * 80)

    tickers = _placeholder_insider_screen()
    if not tickers:
        logger.info("INSIDER TRACKER: no insider clusters available (data source not configured)")
        logger.info("=" * 80)
        return []

    candidates: List[InsiderCandidate] = []
    for sym in tickers:
        try:
            info = yf.Ticker(sym).info
        except Exception as e:
            logger.error(f"{sym}: failed to load info: {e}")
            continue

        if not info:
            continue

        mcap = float(info.get("marketCap") or 0)
        avg_vol = float(info.get("averageVolume") or 0)
        price = float(info.get("currentPrice", info.get("regularMarketPrice", 0)) or 0)
        if mcap < MIN_MARKET_CAP or avg_vol < MIN_AVG_VOLUME or price <= 5.0:
            continue

        confidence = 0.7
        reasoning = "Cluster insider buying detected with strong quality filters (placeholder)"
        candidates.append(
            InsiderCandidate(
                ticker=sym,
                current_price=price,
                confidence=confidence,
                reasoning=reasoning,
            )
        )

    result = [c.to_orchestrator_candidate() for c in candidates]
    logger.info(f"INSIDER TRACKER: emitting {len(result)} candidates")
    logger.info("=" * 80)
    return result


if __name__ == "__main__":
    out = insider_buying_strategy()
    print(f"Insider tracker candidates: {len(out)}")

