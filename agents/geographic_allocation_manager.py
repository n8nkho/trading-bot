from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def load_international_universe(path: Path | None = None) -> dict[str, Any]:
    p = path or Path("config") / "international_universe.yaml"
    if not p.exists():
        return {"regions": [], "allocation": {"international_sleeve_pct": 20, "max_region_pct": 8}}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def build_geographic_plan(*, portfolio_value: float, regime: str | None = None, vix: float | None = None) -> dict[str, Any]:
    cfg = load_international_universe()
    allocation = cfg.get("allocation") or {}
    intl_pct = float(allocation.get("international_sleeve_pct", 20))
    max_region_pct = float(allocation.get("max_region_pct", 8))
    total_capital = round(float(portfolio_value) * (intl_pct / 100.0), 2)
    regions = cfg.get("regions") or []
    picks = []
    for row in regions:
        symbol = row.get("symbol")
        if not symbol:
            continue
        picks.append(
            {
                "symbol": symbol,
                "region": row.get("region", "Unknown"),
                "hedge_symbol": row.get("hedge_symbol"),
                "target_pct_total_book": max_region_pct,
                "target_usd": round(float(portfolio_value) * (max_region_pct / 100.0), 2),
            }
        )
    return {
        "timestamp": datetime.now().isoformat(),
        "regime": regime or "UNKNOWN",
        "vix": vix,
        "international_sleeve_pct": intl_pct,
        "international_capital_usd": total_capital,
        "max_region_pct": max_region_pct,
        "allocations": picks,
        "rebalance_cadence": "monthly",
        "hedge_rule": "activate region hedge if regional drawdown > 4% or DXY trend spikes",
    }


def run_geographic_allocation_manager(*, portfolio_value: float, data_dir: Path, regime: str | None = None, vix: float | None = None) -> dict[str, Any]:
    out = build_geographic_plan(portfolio_value=portfolio_value, regime=regime, vix=vix)
    path = data_dir / f"geographic_allocation_plan_{datetime.now().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out

