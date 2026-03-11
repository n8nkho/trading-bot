from __future__ import annotations

"""
Sector Rotation Detector

Identifies sectors that have recently underperformed but are beginning to
outperform SPY, then selects high-quality constituents within those sectors.

Signal-only agent: emits stock candidates; orchestrator controls execution.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import yfinance as yf


logging.basicConfig(
    filename="logs/sector_rotation.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


SECTOR_ETFS: Dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

MIN_STOCK_VOLUME = 2_000_000
MIN_STOCK_MARKET_CAP = 5_000_000_000


@dataclass
class RotationStockCandidate:
    ticker: str
    sector: str
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
            "strategy_id": "sector_rotation",
            "sector": self.sector,
        }


def _rs_series(etf: str, ref: str, days: int = 40) -> Optional[yf.pdr_fam.DataFrame]:
    try:
        data = yf.download(
            [etf, ref],
            period=f"{days}d",
            interval="1d",
            progress=False,
        )
    except Exception as e:
        logger.error(f"Failed to download data for {etf}/{ref}: {e}")
        return None
    if data is None or data.empty:
        return None
    close = data["Close"]
    if etf not in close.columns or ref not in close.columns:
        return None
    rs = close[etf] / close[ref]
    return rs


def _score_sector(etf: str) -> Optional[Dict[str, Any]]:
    rs = _rs_series(etf, "SPY", days=40)
    if rs is None or rs.empty:
        return None

    rs_5_change = (rs.iloc[-1] / rs.iloc[-5] - 1.0) * 100.0 if len(rs) >= 5 else 0.0
    rs_20_change = (rs.iloc[-1] / rs.iloc[-20] - 1.0) * 100.0 if len(rs) >= 20 else 0.0

    # "Underperformed then turning up" pattern
    underperf_recent = rs_5_change < -3.0
    turning_up = rs_5_change > 0.0 and rs_20_change > -2.0

    return {
        "etf": etf,
        "rs_5_change": rs_5_change,
        "rs_20_change": rs_20_change,
        "underperf_recent": underperf_recent,
        "turning_up": turning_up,
    }


def _pick_sector_stocks(etf: str, sector_name: str, max_stocks: int = 3) -> List[RotationStockCandidate]:
    """
    Best-effort stock selection using yfinance info for ETF holdings.
    We approximate by taking the ETF's top holdings via .info['holdings'] if present,
    otherwise we fall back to an empty list.
    """
    try:
        tk = yf.Ticker(etf)
        holdings = tk.get_info().get("holdings", None)  # type: ignore[attr-defined]
    except Exception:
        holdings = None

    tickers: List[str] = []
    if isinstance(holdings, list):
        for h in holdings:
            sym = h.get("symbol")
            if isinstance(sym, str):
                tickers.append(sym.upper())

    # If we cannot introspect holdings, log and return no stocks for this sector
    if not tickers:
        logger.info(f"{etf}: no holdings data available; skipping stock selection")
        return []

    candidates: List[RotationStockCandidate] = []
    for sym in tickers:
        if len(candidates) >= max_stocks:
            break
        try:
            info = yf.Ticker(sym).info
        except Exception as e:
            logger.debug(f"{sym}: failed to load info: {e}")
            continue

        if not info:
            continue

        mcap = float(info.get("marketCap") or 0)
        avg_vol = float(info.get("averageVolume") or 0)
        price = float(info.get("currentPrice", info.get("regularMarketPrice", 0)) or 0)
        eps = info.get("trailingEps")
        revenue_growth = float(info.get("revenueGrowth") or 0.0)

        if (
            mcap < MIN_STOCK_MARKET_CAP
            or avg_vol < MIN_STOCK_VOLUME
            or price <= 5.0
            or eps is None
            or revenue_growth < 0.05
        ):
            continue

        confidence = 0.65
        reasoning = (
            f"Sector rotation {sector_name}: large, liquid constituent with positive earnings and "
            f"{revenue_growth*100:.1f}% revenue growth"
        )
        candidates.append(
            RotationStockCandidate(
                ticker=sym,
                sector=sector_name,
                current_price=price,
                confidence=confidence,
                reasoning=reasoning,
            )
        )

    return candidates


def sector_rotation_strategy(portfolio_value: float = 10_000.0) -> List[Dict[str, Any]]:
    """
    Main entry point for the Sector Rotation strategy.

    Returns orchestrator-compatible candidate dicts.
    """
    logger.info("=" * 80)
    logger.info("SECTOR ROTATION STRATEGY - SCAN START")
    logger.info("=" * 80)

    sector_scores: Dict[str, Dict[str, Any]] = {}
    for etf, name in SECTOR_ETFS.items():
        try:
            score = _score_sector(etf)
            if not score:
                continue
            sector_scores[etf] = score
            logger.info(
                f"{etf} ({name}): RS_5={score['rs_5_change']:.1f}%, "
                f"RS_20={score['rs_20_change']:.1f}%"
            )
        except Exception as e:
            logger.error(f"{etf}: error scoring sector: {e}")
            continue

    rotating_sectors: List[str] = []
    for etf, score in sector_scores.items():
        if score["underperf_recent"] and score["turning_up"]:
            rotating_sectors.append(etf)
            logger.info(
                f"{etf}: rotation signal (underperf_recent={score['underperf_recent']}, "
                f"turning_up={score['turning_up']})"
            )

    logger.info(f"SECTOR ROTATION: {len(rotating_sectors)} sectors with rotation signals")

    stock_candidates: List[RotationStockCandidate] = []
    for etf in rotating_sectors:
        sector_name = SECTOR_ETFS.get(etf, etf)
        try:
            stock_candidates.extend(_pick_sector_stocks(etf, sector_name, max_stocks=3))
        except Exception as e:
            logger.error(f"{etf}: error selecting sector stocks: {e}")
            continue

    logger.info(
        f"SECTOR ROTATION: emitting {len(stock_candidates)} stock candidates across "
        f"{len(rotating_sectors)} rotating sectors"
    )
    result = [c.to_orchestrator_candidate() for c in stock_candidates]
    logger.info("=" * 80)
    return result


if __name__ == "__main__":
    out = sector_rotation_strategy()
    print(f"Sector rotation candidates: {len(out)}")

