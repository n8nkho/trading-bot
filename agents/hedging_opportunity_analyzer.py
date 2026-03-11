"""
Hedging Opportunity Analyzer Agent

Assesses missed safe opportunities across hedging strategies by comparing:
- Fortress reports (recommended bond targets, commodities, VIX, pairs, etc.)
- Current regime and VIX
- Optional: actual positions (e.g. TLT, GLD) when available

Produces recommendations to improve hedge capture while keeping risk goals.
Output: data/hedging_recommendations.json (consumed by Command Center).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DATA_DIR = Path("data")
LOGS_DIR = Path("logs")
OUTPUT_FILE = DATA_DIR / "hedging_recommendations.json"

logging.basicConfig(
    filename=LOGS_DIR / "hedging_opportunity_analyzer.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Thresholds for "missed opportunity" or actionable suggestions
VIX_ELEVATED = 22.0
VIX_HIGH = 28.0
REGIME_RISK_OFF = "RISK_OFF"
REGIME_CRASH = "CRASH"


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


def _load_latest_fortress_report() -> dict | None:
    pattern = list(DATA_DIR.glob("fortress_report_*.json"))
    if not pattern:
        return None
    pattern.sort(key=lambda p: p.name, reverse=True)
    return _read_json(pattern[0], {})


def _load_regime() -> dict:
    return _read_json(DATA_DIR / "market_regime.json", {})


def _load_positions() -> list:
    raw = _read_json(DATA_DIR / "positions.json", [])
    if isinstance(raw, list):
        return raw
    return raw.get("positions", raw.get("positions_list", []))


def _infer_hedge_positions(positions: list) -> dict:
    """Infer current hedge exposure from position tickers (TLT, GLD, etc.)."""
    bond_etfs = {"TLT", "IEF", "SHY", "BND", "AGG"}
    commodity_etfs = {"GLD", "SLV", "USO", "DBA", "GSG"}
    out = {"bonds_value": 0.0, "commodities_value": 0.0, "has_vix": False}
    for p in positions:
        if not isinstance(p, dict):
            continue
        ticker = (p.get("ticker") or p.get("symbol") or "").upper()
        value = float(p.get("value") or p.get("market_value") or 0)
        qty = int(p.get("qty") or p.get("shares") or 0)
        entry = float(p.get("entry_price") or 0)
        if qty and entry and not value:
            value = qty * entry
        if ticker in bond_etfs:
            out["bonds_value"] += value
        elif ticker in commodity_etfs:
            out["commodities_value"] += value
        elif "VIX" in ticker or ticker in {"UVXY", "VXX", "SVXY"}:
            out["has_vix"] = True
    return out


def run_hedging_opportunity_analysis() -> dict:
    """
    Analyze fortress reports and regime to produce hedging recommendations.
    """
    logger.info("=" * 80)
    logger.info("HEDGING OPPORTUNITY ANALYZER - START")
    logger.info("=" * 80)

    result = {
        "timestamp": datetime.now().isoformat(),
        "recommendations": [],
        "summary": {},
    }

    try:
        report = _load_latest_fortress_report()
        regime_data = _load_regime()
        positions = _load_positions()
        regime = (regime_data.get("regime") or "NEUTRAL").upper()
        vix = regime_data.get("vix")
        if vix is not None:
            vix = float(vix)

        result["summary"] = {
            "regime": regime,
            "vix": vix,
            "has_fortress_report": report is not None and bool(report),
        }

        if not report:
            result["recommendations"].append({
                "title": "No fortress report yet",
                "body": "Run fortress hedging (orchestrator.py fortress) to generate hedge recommendations and enable hedging opportunity analysis.",
                "action": "Schedule or run orchestrator.py fortress.",
                "severity": "low",
            })
            _save(result)
            return result

        strategies = report.get("strategies") or {}
        mc = report.get("market_conditions") or {}
        target_alloc = report.get("target_allocations") or {}

        # VIX: missed opportunity if VIX elevated and we skipped insurance
        vix_ins = strategies.get("vix_insurance") or {}
        if isinstance(vix_ins, dict) and vix_ins.get("action") == "SKIP":
            if vix is not None:
                if vix >= VIX_HIGH:
                    result["recommendations"].append({
                        "title": "VIX elevated; VIX insurance currently skipped",
                        "body": f"VIX at {vix:.1f} (high). Fortress is in budget mode and skips VIX insurance. Consider adding a small hedge when budget allows.",
                        "action": "Review BUDGET_MODE in fortress_orchestrator; consider VIX hedge in RISK_OFF.",
                        "severity": "medium",
                    })
                elif vix >= VIX_ELEVATED:
                    result["recommendations"].append({
                        "title": "VIX above 22; hedge mix may need review",
                        "body": f"VIX at {vix:.1f}. Ensure bonds and diversification are at target; VIX insurance is currently skipped (budget mode).",
                        "action": "Confirm bond/commodity targets are met.",
                        "severity": "low",
                    })

        # Regime alignment
        if regime == REGIME_RISK_OFF or regime == REGIME_CRASH:
            bonds_target = (strategies.get("bonds") or {}).get("target")
            if bonds_target is not None:
                result["recommendations"].append({
                    "title": "Regime is RISK_OFF/CRASH – bonds target active",
                    "body": f"Bond target from fortress: ${bonds_target:,.0f}. Ensure portfolio has defensive allocation.",
                    "action": "Review positions; consider adding TLT/IEF if below target.",
                    "severity": "medium",
                })
            if target_alloc.get("commodities", 0) >= 0.1:
                result["recommendations"].append({
                    "title": "Commodity allocation elevated in this regime",
                    "body": f"Target allocation suggests {100 * target_alloc.get('commodities', 0):.0f}% commodities. Check commodities strategy output.",
                    "action": "Run commodity_trader logic; consider GLD/DBA if aligned.",
                    "severity": "low",
                })

        # Bonds gap: recommended target vs inferred position
        hedge = _infer_hedge_positions(positions)
        bonds_rec = (strategies.get("bonds") or {}).get("target")
        if bonds_rec is not None and hedge["bonds_value"] is not None:
            try:
                target = float(bonds_rec)
                current = float(hedge["bonds_value"])
                if target > 0 and current < target * 0.5:
                    result["recommendations"].append({
                        "title": "Bond allocation below target",
                        "body": f"Bond target ${target:,.0f}; inferred bond positions ~${current:,.0f}. Consider adding duration (TLT/IEF) for hedge.",
                        "action": "Review Alpaca positions (TLT, IEF); add if below target and regime supports.",
                        "severity": "low",
                    })
            except (TypeError, ValueError):
                pass

        # Pairs: actionable opportunity mentioned in report
        pairs = strategies.get("pairs_trading") or {}
        if isinstance(pairs, dict) and pairs.get("action") not in (None, "NONE", "HOLD"):
            opp = pairs.get("opportunity") or pairs
            pair_str = str(opp.get("pair", opp.get("long_ticker", "")) + "/" + str(opp.get("short_ticker", "")))
            result["recommendations"].append({
                "title": "Pairs trading opportunity in report",
                "body": f"Fortress reported pairs opportunity: {pair_str}. Review if still valid and within risk limits.",
                "action": "Check pairs_trading strategy and execution path.",
                "severity": "low",
            })

        # Commodities null or NONE
        comm = strategies.get("commodities")
        if comm is None or (isinstance(comm, dict) and comm.get("action") in (None, "NONE")):
            if regime == REGIME_RISK_OFF and (target_alloc.get("commodities") or 0) > 0.05:
                result["recommendations"].append({
                    "title": "Commodities signal missing in RISK_OFF",
                    "body": "Target allocation includes commodities but strategy returned no action. Check commodity_trader and data.",
                    "action": "Run agents.commodity_trader; ensure USD/commodity data available.",
                    "severity": "low",
                })

        # Hedging goals reminder
        result["recommendations"].append({
            "title": "Hedging goals reminder",
            "body": "Keep bonds and diversification aligned with regime; preserve capital with stop losses and position limits.",
            "action": "No action required.",
            "severity": "low",
        })

        _save(result)
        logger.info("Hedging opportunity analysis complete: %d recommendations", len(result["recommendations"]))
    except Exception as e:
        logger.exception("Hedging opportunity analysis failed: %s", e)
        result["recommendations"] = [{
            "title": "Hedging analyzer error",
            "body": str(e)[:200],
            "action": "Check logs/hedging_opportunity_analyzer.log",
            "severity": "medium",
        }]

    logger.info("=" * 80)
    return result


def _save(result: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    try:
        with open(OUTPUT_FILE, "w") as f:
            json.dump(result, f, indent=2)
    except Exception as e:
        logger.error("Failed to write %s: %s", OUTPUT_FILE, e)


if __name__ == "__main__":
    run_hedging_opportunity_analysis()
