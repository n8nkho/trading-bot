from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.analysts import fundamentals, macro, momentum, sentiment


def run_analyst_ensemble(*, opportunities: list[dict[str, Any]], data_dir: Path) -> dict[str, Any]:
    reviewers = [fundamentals.score, momentum.score, macro.score, sentiment.score]
    out_rows: list[dict[str, Any]] = []
    for opp in opportunities:
        symbol = opp.get("symbol", "UNKNOWN")
        scores = [float(fn(symbol, opp)) for fn in reviewers]
        consensus = sum(scores) / len(scores)
        out_rows.append(
            {
                "symbol": symbol,
                "consensus_score": round(consensus, 4),
                "recommendation": "BUY" if consensus >= 0.62 else "WATCH",
                "component_scores": {
                    "fundamentals": scores[0],
                    "momentum": scores[1],
                    "macro": scores[2],
                    "sentiment": scores[3],
                },
            }
        )
    out = {
        "timestamp": datetime.now().isoformat(),
        "analyst_count": 4,
        "evaluated": len(out_rows),
        "recommendations": sorted(out_rows, key=lambda x: x["consensus_score"], reverse=True),
    }
    path = data_dir / f"analyst_consensus_{datetime.now().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out

