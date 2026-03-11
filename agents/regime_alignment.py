"""
Regime–Strategy Alignment Agent

Compares current regime (regime_center) with active strategies, bond target, and hedging;
outputs recommendations so sizing and activity align with near-zero loss and high win rate.
Output: data/regime_recommendations.json (consumed by Command Center).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path("data")
LOGS_DIR = Path("logs")
OUTPUT_FILE = DATA_DIR / "regime_recommendations.json"

logging.basicConfig(
    filename=LOGS_DIR / "regime_alignment.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return default


def run_regime_alignment() -> dict:
    """
    Produce regime–strategy alignment recommendations.
    Returns dict with 'recommendations' list (title, body, action, severity).
    """
    recommendations = []
    try:
        regime_data = _read_json(DATA_DIR / "market_regime.json", {})
        regime = (regime_data.get("regime") or "NEUTRAL").upper()
        vix = regime_data.get("vix")
        positions = _read_json(DATA_DIR / "positions.json", [])
        if not isinstance(positions, list):
            positions = positions.get("positions", positions.get("positions_list", []))
        fortress = None
        for p in DATA_DIR.glob("fortress_report_*.json"):
            fortress = _read_json(p, {})
            break

        # CRASH: recommend pause equity, bonds only
        if regime == "CRASH":
            recommendations.append({
                "title": "Regime CRASH – reduce equity exposure",
                "body": "Market regime is CRASH (VIX or trend). Auto-execution already uses reduced size and trade count. Consider pausing new equity entries until regime improves; bond rebalance only.",
                "action": "Monitor regime_center; optional: disable auto-equity in Command Center until NEUTRAL/RISK_ON.",
                "severity": "high",
            })

        # RISK_OFF: reinforce bonds and defensive names
        elif regime == "RISK_OFF":
            recommendations.append({
                "title": "Regime RISK_OFF – defensive alignment",
                "body": f"Regime RISK_OFF (VIX={vix}). Equity sizing and daily trade cap are already reduced. Defensive watchlist is prepended to screener in RISK_OFF.",
                "action": "Ensure bond rebalance runs; review data/defensive_recommendations.json.",
                "severity": "medium",
            })

        # RISK_ON: optional note that sizing is elevated
        elif regime == "RISK_ON":
            recommendations.append({
                "title": "Regime RISK_ON – normal opportunity capture",
                "body": "Regime RISK_ON. Position size multiplier and confidence thresholds allow normal opportunity capture. Strict filters (drop band, RSI, volume) remain.",
                "action": "None. Keep filters and stop loss unchanged.",
                "severity": "low",
            })

        # Bond target vs regime (if fortress report exists)
        if fortress and regime in ("RISK_OFF", "CRASH"):
            rec = fortress.get("recommendations") or fortress.get("bond_target")
            if rec:
                recommendations.append({
                    "title": "Hedge target vs regime",
                    "body": f"Fortress report suggests bond/hedge target. Regime {regime} supports higher bond allocation.",
                    "action": "Run hedge rebalance if not at target (orchestrator hedge_rebalance).",
                    "severity": "low",
                })

    except Exception as e:
        logger.exception("Regime alignment failed: %s", e)
        recommendations.append({
            "title": "Regime alignment check failed",
            "body": str(e),
            "action": "Check logs/regime_alignment.log.",
            "severity": "low",
        })

    result = {
        "timestamp": datetime.now().isoformat(),
        "regime": _read_json(DATA_DIR / "market_regime.json", {}).get("regime", "UNKNOWN"),
        "recommendations": recommendations[:10],
    }
    try:
        DATA_DIR.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            json.dump(result, f, indent=2)
        logger.info("Wrote %s with %d recommendations", OUTPUT_FILE, len(recommendations))
    except Exception as e:
        logger.error("Failed to write %s: %s", OUTPUT_FILE, e)
    return result


if __name__ == "__main__":
    run_regime_alignment()
