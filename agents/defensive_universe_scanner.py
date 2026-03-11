"""
Defensive Universe Scanner

Scans the screening universe (or a broad set) for names that are relatively
defensive: low beta, positive dividend, held up in recent drawdowns.
Output: data/defensive_watchlist.json; optionally contributes to
data/opportunity_recommendations.json or a dedicated rec for Command Center.

Aligned with overarching goals: near-zero loss, high win rate—adds optional
low-correlation, capital-preservation names without loosening core criteria.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yfinance as yf

DATA_DIR = Path("data")
LOGS_DIR = Path("logs")
OUTPUT_FILE = DATA_DIR / "defensive_watchlist.json"
RECOMMENDATION_FILE = DATA_DIR / "defensive_recommendations.json"

logging.basicConfig(
    filename=LOGS_DIR / "defensive_scanner.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Criteria for "defensive" (conservative)
MAX_BETA = 1.1
MIN_DIVIDEND_YIELD = 0.0  # Prefer > 0 when available
MIN_MARKET_CAP = 5_000_000_000
MAX_TICKERS = 30


def _get_seed_tickers() -> list[str]:
    """Seed from screener base or S&P 100 style list."""
    try:
        from agents.screener_agent import get_sp500_tickers
        return get_sp500_tickers()[:80]
    except Exception:
        return ["AAPL", "MSFT", "JNJ", "PG", "KO", "PEP", "WMT", "JPM", "XOM", "UNH"]


def run_defensive_scan() -> dict[str, Any]:
    """
    Scan for defensive names and write watchlist + optional recommendation.
    """
    logger.info("=" * 80)
    logger.info("DEFENSIVE UNIVERSE SCANNER - START")
    logger.info("=" * 80)

    result = {
        "timestamp": datetime.now().isoformat(),
        "tickers": [],
        "recommendations": [],
    }

    try:
        seed = _get_seed_tickers()
        defensive = []
        for ticker in seed:
            try:
                t = yf.Ticker(ticker)
                info = t.info or {}
                beta = info.get("beta")
                if beta is not None and beta > MAX_BETA:
                    continue
                mcap = float(info.get("marketCap") or 0)
                if mcap < MIN_MARKET_CAP:
                    continue
                div_yield = info.get("dividendYield") or 0
                if isinstance(div_yield, (int, float)) and div_yield < 0:
                    continue
                defensive.append({
                    "ticker": ticker,
                    "beta": beta,
                    "dividendYield": div_yield,
                    "marketCap": mcap,
                })
            except Exception as e:
                logger.debug("%s: %s", ticker, e)
                continue
        # Sort by beta (prefer lower), then by dividend
        defensive.sort(key=lambda x: (x.get("beta") or 2, -(x.get("dividendYield") or 0)))
        result["tickers"] = [x["ticker"] for x in defensive[:MAX_TICKERS]]

        DATA_DIR.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            json.dump({"timestamp": result["timestamp"], "tickers": result["tickers"]}, f, indent=2)

        # Single recommendation for Command Center when we have a list
        try:
            regime_data = json.loads((DATA_DIR / "market_regime.json").read_text()) if (DATA_DIR / "market_regime.json").exists() else {}
            regime = (regime_data.get("regime") or "NEUTRAL").upper()
        except Exception:
            regime = "NEUTRAL"

        result["recommendations"].append({
            "title": "Defensive watchlist updated",
            "body": f"{len(result['tickers'])} defensive names (low beta, quality). In RISK_OFF, consider these for capital preservation.",
            "action": "See data/defensive_watchlist.json; optional: prefer these in screener when regime is RISK_OFF.",
            "severity": "low",
        })
        with open(RECOMMENDATION_FILE, "w") as f:
            json.dump({
                "timestamp": result["timestamp"],
                "recommendations": result["recommendations"],
                "regime": regime,
            }, f, indent=2)
        logger.info("Defensive scan complete: %d tickers", len(result["tickers"]))
    except Exception as e:
        logger.exception("Defensive scan failed: %s", e)
        result["recommendations"] = [{"title": "Defensive scanner error", "body": str(e)[:200], "action": "Check logs/defensive_scanner.log", "severity": "medium"}]

    logger.info("=" * 80)
    return result


if __name__ == "__main__":
    run_defensive_scan()
