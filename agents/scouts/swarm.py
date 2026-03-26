from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.scouts import earnings_scout, event_scout, macro_scout, technical_scout, volatility_scout


def run_scout_swarm(*, data_dir: Path) -> dict[str, Any]:
    scouts = {
        "macro_scout": macro_scout.scan(),
        "event_scout": event_scout.scan(),
        "earnings_scout": earnings_scout.scan(),
        "technical_scout": technical_scout.scan(),
        "volatility_scout": volatility_scout.scan(),
    }
    opportunities: list[dict[str, Any]] = []
    for source, items in scouts.items():
        for row in items:
            entry = dict(row)
            entry["source"] = source
            opportunities.append(entry)
    out = {
        "timestamp": datetime.now().isoformat(),
        "scout_count": len(scouts),
        "opportunity_count": len(opportunities),
        "opportunities": sorted(opportunities, key=lambda x: float(x.get("score", 0.0)), reverse=True),
    }
    path = data_dir / f"scout_opportunity_queue_{datetime.now().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out

