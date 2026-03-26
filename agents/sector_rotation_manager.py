from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SECTOR_ETFS = [
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
]


@dataclass
class SectorSignal:
    sector: str
    rel_strength_score: float
    weight_pct: float


def _macro_quadrant(vix: float | None) -> str:
    if vix is None:
        return "unknown"
    if vix < 16:
        return "growth_disinflation"
    if vix < 25:
        return "balanced"
    if vix < 35:
        return "inflation_shock"
    return "recession_stress"


def build_monthly_rotation_signal(
    *,
    sector_history: dict[str, Any],
    vix: float | None,
    portfolio_value: float,
    allocation_pct: float = 30.0,
) -> dict[str, Any]:
    perf = sector_history.get("monthly_relative_strength") or {}
    ranked = sorted(
        [(k, float(v)) for k, v in perf.items() if k in SECTOR_ETFS],
        key=lambda x: x[1],
        reverse=True,
    )
    top = ranked[:3]
    if not top:
        top = [("XLK", 0.0), ("XLF", 0.0), ("XLV", 0.0)]
    # 50/30/20 split across top-3 sectors.
    weights = [50.0, 30.0, 20.0]
    signals = [
        SectorSignal(sector=s, rel_strength_score=score, weight_pct=weights[idx]).__dict__
        for idx, (s, score) in enumerate(top)
    ]
    sleeve_capital = float(portfolio_value) * (allocation_pct / 100.0)
    return {
        "timestamp": datetime.now().isoformat(),
        "macro_quadrant": _macro_quadrant(vix),
        "vix": vix,
        "allocation_pct": allocation_pct,
        "sleeve_capital_usd": round(sleeve_capital, 2),
        "signals": signals,
        "rebalance_rule": "first_trading_day_each_month",
    }


def run_sector_rotation_manager(
    *,
    data_dir: Path,
    portfolio_value: float,
    vix: float | None = None,
) -> dict[str, Any]:
    # Runtime override in data/, source-controlled baseline in config/.
    hist_path = data_dir / "sector_performance_history.json"
    cfg_hist_path = Path("config") / "sector_performance_history.json"
    if hist_path.exists():
        raw = json.loads(hist_path.read_text(encoding="utf-8"))
    elif cfg_hist_path.exists():
        raw = json.loads(cfg_hist_path.read_text(encoding="utf-8"))
    else:
        raw = {"monthly_relative_strength": {"XLK": 1.1, "XLF": 0.8, "XLV": 0.6}}
    out = build_monthly_rotation_signal(
        sector_history=raw,
        vix=vix,
        portfolio_value=portfolio_value,
        allocation_pct=30.0,
    )
    out_path = data_dir / f"sector_rotation_signal_{datetime.now().strftime('%Y%m')}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out

