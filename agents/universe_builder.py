"""
Universe Builder Agent

Expands the stock universe beyond the hand-curated S&P + Russell lists by
finding additional liquid, volatile names using simple, conservative rules.

Output:
  - data/universe_extra.json: ["TICK1", "TICK2", ...]

The screener then merges this file into its base universe, while all existing
drop/RSI/volume/risk rules remain unchanged.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

import yfinance as yf

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    filename=log_dir / "universe_builder.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = DATA_DIR / "universe_extra.json"


def get_seed_tickers() -> List[str]:
    """
    Get a broad seed list from yfinance index helpers.
    This is deliberately larger than the base S&P+Russell lists.
    """
    try:
        from yfinance.shared import tickers_sp500, tickers_nasdaq
    except Exception:
        # Fallback: minimal list if helpers are unavailable
        return []
    tickers = set()
    try:
        tickers.update(tickers_sp500() or [])
    except Exception as e:
        logger.warning(f"Failed to load full S&P 500 tickers: {e}")
    try:
        tickers.update(tickers_nasdaq() or [])
    except Exception as e:
        logger.warning(f"Failed to load Nasdaq tickers: {e}")
    return sorted({t.upper() for t in tickers if isinstance(t, str)})


def build_universe_extra(portfolio_value: float = 50_000, max_candidates: int = 400) -> List[str]:
    """
    Build an expanded universe of additional liquid, volatile tickers.

    Rules:
      - Start from broad index tickers (S&P + Nasdaq).
      - Filter for avgVolume > 2M, price > $5.
      - Roughly prefer higher beta / volatility via 1-month ATR% > 2%.
      - Limit to top `max_candidates` names by volume.
    """
    logger.info("UNIVERSE_BUILDER: starting build_universe_extra()")

    seed = get_seed_tickers()
    if not seed:
        logger.warning("UNIVERSE_BUILDER: no seed tickers found; writing empty universe_extra.json")
        OUTPUT_FILE.write_text("[]")
        return []

    logger.info(f"UNIVERSE_BUILDER: seed universe size={len(seed)}")

    scored: List[tuple[float, str]] = []
    for sym in seed:
        try:
            info = yf.Ticker(sym).info
            avg_vol = float(info.get("averageVolume", 0) or 0)
            price = float(info.get("currentPrice", info.get("regularMarketPrice", 0)) or 0)
            if avg_vol <= 2_000_000 or price <= 5:
                continue

            # Simple volatility proxy: 1-month ATR% (approx via high/low range)
            hist = yf.Ticker(sym).history(period="1mo")
            if hist is None or hist.empty:
                continue
            high = hist["High"].max()
            low = hist["Low"].min()
            if low <= 0:
                continue
            atr_pct = float((high - low) / low) * 100.0
            if atr_pct < 2.0:
                continue

            scored.append((avg_vol, sym))
        except Exception:
            continue

    # Sort by volume descending and keep top N
    scored.sort(key=lambda x: x[0], reverse=True)
    extra = [sym for _vol, sym in scored[:max_candidates]]

    logger.info(f"UNIVERSE_BUILDER: selected {len(extra)} extra tickers")
    try:
        with open(OUTPUT_FILE, "w") as f:
            json.dump(extra, f, indent=2)
        logger.info(f"UNIVERSE_BUILDER: wrote {len(extra)} tickers to {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"UNIVERSE_BUILDER: failed to write universe_extra.json: {e}")

    return extra


if __name__ == "__main__":
    out = build_universe_extra()
    print(f"Universe extra size: {len(out)}")
    if out:
        print("Sample:", out[:20])

