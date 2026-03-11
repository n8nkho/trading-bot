from __future__ import annotations

"""
Unusual Options Flow Tracker

This agent is intentionally implemented as a *skeleton* pending integration
with a paid options flow provider (e.g. Unusual Whales, FlowAlgo).

Current behavior:
- Reads a (non-required) JSON file data/options_flow_sample.json if present.
- Applies basic filters to that offline sample.
- If no data file exists, logs that the flow tracker is disabled and returns [].
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


logging.basicConfig(
    filename="logs/flow_tracker.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


DATA_DIR = Path("data")
FLOW_SAMPLE_FILE = DATA_DIR / "options_flow_sample.json"


@dataclass
class FlowCandidate:
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
            "strategy_id": "options_flow",
        }


def _load_flow_sample() -> List[Dict[str, Any]]:
    if not FLOW_SAMPLE_FILE.exists():
        logger.info(
            "FLOW TRACKER: options_flow_sample.json not found; "
            "flow-based strategy is effectively disabled until data is configured."
        )
        return []
    try:
        with open(FLOW_SAMPLE_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.error(f"Failed to read {FLOW_SAMPLE_FILE}: {e}")
        return []


def flow_tracker_strategy(portfolio_value: float = 10_000.0) -> List[Dict[str, Any]]:
    """
    Main entry point for the Unusual Options Flow strategy.

    Uses offline sample data if present; otherwise acts as a no-op that only
    logs its disabled state. This keeps the architecture ready while avoiding
    brittle scraping or paid API dependencies by default.
    """
    logger.info("=" * 80)
    logger.info("OPTIONS FLOW STRATEGY - SCAN START")
    logger.info("=" * 80)

    raw_flows = _load_flow_sample()
    if not raw_flows:
        logger.info("FLOW TRACKER: no flow data available; emitting 0 candidates")
        logger.info("=" * 80)
        return []

    candidates: List[FlowCandidate] = []
    for flow in raw_flows:
        try:
            sym = str(flow.get("symbol") or "").upper()
            notional = float(flow.get("notional") or 0.0)
            direction = (flow.get("side") or "").lower()
            premium = float(flow.get("premium") or 0.0)
            current_price = float(flow.get("underlying_price") or 0.0)

            if not sym or current_price <= 0:
                continue
            if notional < 1_000_000 or premium < 50_000:
                continue

            confidence = 0.7
            reasoning = (
                f"Unusual {direction} options flow: notional ${notional:,.0f}, "
                f"premium ${premium:,.0f}"
            )
            candidates.append(
                FlowCandidate(
                    ticker=sym,
                    current_price=current_price,
                    confidence=confidence,
                    reasoning=reasoning,
                )
            )
        except Exception as e:
            logger.error(f"Error parsing flow record {flow}: {e}")
            continue

    result = [c.to_orchestrator_candidate() for c in candidates]
    logger.info(f"FLOW TRACKER: emitting {len(result)} candidates from sample data")
    logger.info("=" * 80)
    return result


if __name__ == "__main__":
    out = flow_tracker_strategy()
    print(f"Flow tracker candidates: {len(out)}")

