from __future__ import annotations

"""
Earnings Drift Tracker (PEAD-style)

Signal-only agent: scans for recent strong positive earnings reactions and
emits high-quality continuation candidates. Does NOT place orders directly;
orchestrator remains the single execution point.

Current implementation:
- Uses yfinance only (no external earnings/analyst APIs)
- Focuses on a liquid large-cap universe (screener_agent helpers)
- Applies conservative filters on gap, follow-through and liquidity
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import yfinance as yf

from agents.screener_agent import get_sp500_tickers


logging.basicConfig(
    filename="logs/earnings_drift.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


MIN_MARKET_CAP = 1_000_000_000  # $1B
MIN_AVG_VOLUME = 2_000_000
MIN_EARNINGS_GAP_PCT = 7.0
MIN_EARNINGS_VOLUME_MULT = 2.0
MAX_PULLBACK_FROM_HIGH_PCT = 3.0
MIN_DAY2_VOLUME_MULT = 1.5


@dataclass
class DriftCandidate:
    ticker: str
    current_price: float
    confidence: float
    reasoning: str
    day1_gap_pct: float
    day1_volume_mult: float
    days_since_earnings: int

    def to_orchestrator_candidate(self) -> Dict[str, Any]:
        """
        Convert to the generic candidate schema expected by orchestrator.execute_auto_trades().
        """
        return {
            "ticker": self.ticker,
            "current_price": self.current_price,
            "analysis": {
                "confidence": self.confidence,
                "reasoning": self.reasoning,
                "score": None,
            },
            "strategy_id": "earnings_drift",
        }


def _safe_info(ticker: str) -> Optional[Dict[str, Any]]:
    try:
        info = yf.Ticker(ticker).info
        return info or {}
    except Exception as e:
        logger.debug(f"{ticker}: failed to load info: {e}")
        return None


def _recent_earnings_date(ticker: str) -> Optional[datetime]:
    """
    Best-effort earnings date using yfinance calendar/earnings.
    Returns a recent past date if available, otherwise None.
    """
    try:
        tk = yf.Ticker(ticker)
        cal = tk.calendar
        # yfinance may expose 'Earnings Date' as index or column
        if cal is not None and not cal.empty:
            # Try common patterns
            if "Earnings Date" in cal.index:
                raw = cal.loc["Earnings Date"].iloc[0]
            elif "Earnings Date" in cal.columns:
                raw = cal["Earnings Date"].iloc[0]
            else:
                raw = None
            if raw is not None:
                if isinstance(raw, (datetime,)):
                    return raw
                try:
                    return datetime.fromisoformat(str(raw))
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"{ticker}: failed to load calendar: {e}")
    return None


def _evaluate_drift_candidate(ticker: str, as_of: datetime) -> Optional[DriftCandidate]:
    """
    Apply simplified PEAD-style filters using recent daily bars.
    """
    info = _safe_info(ticker)
    if not info:
        return None

    market_cap = float(info.get("marketCap") or 0)
    avg_volume = float(info.get("averageVolume") or 0)
    if market_cap < MIN_MARKET_CAP or avg_volume < MIN_AVG_VOLUME:
        return None

    # Determine earnings date (approximate; skip if too old/unknown)
    earnings_date = _recent_earnings_date(ticker)
    if not earnings_date:
        return None
    days_ago = (as_of.date() - earnings_date.date()).days
    if days_ago < 0 or days_ago > 5:
        return None

    # Fetch ~7 trading days of daily data around earnings
    start = (earnings_date - timedelta(days=7)).strftime("%Y-%m-%d")
    end = (as_of + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        hist = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
    except Exception as e:
        logger.debug(f"{ticker}: failed to load history: {e}")
        return None

    if hist is None or hist.empty or len(hist) < 3:
        return None

    # Find the row closest to earnings_date
    try:
        hist = hist.sort_index()
        day_idx = hist.index.get_loc(earnings_date, method="nearest")
    except Exception:
        # If exact match fails, just take the last row before as a proxy
        prior = hist[hist.index.date <= earnings_date.date()]
        if prior.empty:
            return None
        day_idx = len(prior) - 1

    day1 = hist.iloc[day_idx]
    prev = hist.iloc[day_idx - 1] if day_idx > 0 else None
    if prev is None:
        return None

    prev_close = float(prev["Close"])
    day1_close = float(day1["Close"])
    day1_high = float(day1["High"])
    day1_vol = float(day1["Volume"])
    if prev_close <= 0 or day1_vol <= 0:
        return None

    day1_gap_pct = (day1_close - prev_close) / prev_close * 100.0
    day1_volume_mult = day1_vol / avg_volume if avg_volume > 0 else 0.0

    if day1_gap_pct < MIN_EARNINGS_GAP_PCT or day1_volume_mult < MIN_EARNINGS_VOLUME_MULT:
        return None

    # Entry window: day 2-3 after earnings, must consolidate without deep pullback
    if day_idx + 1 >= len(hist):
        return None

    # Use the latest available bar as "current"
    current_row = hist.iloc[-1]
    current_price = float(current_row["Close"])
    current_vol = float(current_row["Volume"])

    pullback_from_high_pct = (day1_high - current_price) / day1_high * 100.0
    if pullback_from_high_pct > MAX_PULLBACK_FROM_HIGH_PCT:
        return None

    day2plus_volume_mult = current_vol / avg_volume if avg_volume > 0 else 0.0
    if day2plus_volume_mult < MIN_DAY2_VOLUME_MULT:
        return None

    # Basic confidence score: stronger gaps and volume = higher confidence
    confidence = min(
        0.9,
        0.6
        + 0.01 * max(0.0, day1_gap_pct - MIN_EARNINGS_GAP_PCT)
        + 0.02 * max(0.0, day1_volume_mult - MIN_EARNINGS_VOLUME_MULT),
    )
    reasoning = (
        f"Earnings drift: gap +{day1_gap_pct:.1f}%, "
        f"vol {day1_volume_mult:.1f}x, "
        f"pullback {pullback_from_high_pct:.1f}% (<{MAX_PULLBACK_FROM_HIGH_PCT}%)"
    )

    return DriftCandidate(
        ticker=ticker,
        current_price=current_price,
        confidence=confidence,
        reasoning=reasoning,
        day1_gap_pct=day1_gap_pct,
        day1_volume_mult=day1_volume_mult,
        days_since_earnings=days_ago,
    )


def earnings_drift_strategy(portfolio_value: float = 10_000.0) -> List[Dict[str, Any]]:
    """
    Main entry point for the Earnings Drift strategy.

    Returns a list of orchestrator-compatible candidate dicts.
    """
    logger.info("=" * 80)
    logger.info("EARNINGS DRIFT STRATEGY - SCAN START")
    logger.info("=" * 80)

    as_of = datetime.utcnow()
    universe = get_sp500_tickers()
    logger.info(f"Scanning {len(universe)} large-cap tickers for PEAD-style setups")

    candidates: List[DriftCandidate] = []
    for sym in universe:
        try:
            c = _evaluate_drift_candidate(sym, as_of)
            if c:
                candidates.append(c)
                logger.info(
                    f"{sym}: drift candidate (gap={c.day1_gap_pct:.1f}%, "
                    f"vol={c.day1_volume_mult:.1f}x, days_since_earnings={c.days_since_earnings})"
                )
        except Exception as e:
            logger.error(f"{sym}: error evaluating drift candidate: {e}")
            continue

    logger.info(f"EARNINGS DRIFT: found {len(candidates)} raw candidates")

    # For now, we return candidates as signals only; auto-execution is still governed
    # by orchestrator confidence thresholds and runtime switches.
    result = [c.to_orchestrator_candidate() for c in candidates]

    logger.info(f"EARNINGS DRIFT: emitting {len(result)} orchestrator candidates")
    logger.info("=" * 80)
    return result


if __name__ == "__main__":
    out = earnings_drift_strategy()
    print(f"Earnings drift candidates: {len(out)}")

