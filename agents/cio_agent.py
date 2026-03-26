from __future__ import annotations

import glob
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_latest_json(pattern: str) -> dict[str, Any]:
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return {}
    try:
        return json.loads(Path(files[0]).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _derive_directive(regime: str, vix: float | None) -> tuple[str, float]:
    rg = (regime or "UNKNOWN").upper()
    if rg == "RISK_OFF" or (vix is not None and vix >= 32):
        return "DEFENSIVE", 0.74
    if rg in {"RISK_ON", "BULL"} and (vix is not None and vix < 20):
        return "OFFENSIVE", 0.72
    return "BALANCED", 0.68


def run_cio_cycle(*, data_dir: Path) -> dict[str, Any]:
    fortress = _load_latest_json(str(data_dir / "fortress_report_*.json"))
    sleeves = _load_latest_json(str(data_dir / "multi_timeframe_plan_*.json"))
    sector = _load_latest_json(str(data_dir / "sector_rotation_signal_*.json"))
    geo = _load_latest_json(str(data_dir / "geographic_allocation_plan_*.json"))
    regime = str(fortress.get("market_regime") or "UNKNOWN")
    mc = fortress.get("market_conditions") or {}
    try:
        vix = float(mc.get("vix")) if mc.get("vix") is not None else None
    except (TypeError, ValueError):
        vix = None
    directive, conf = _derive_directive(regime, vix)
    tilts = {
        "DEFENSIVE": {"day_trading": 20, "swing_trading": 35, "position_trading": 45},
        "BALANCED": {"day_trading": 30, "swing_trading": 40, "position_trading": 30},
        "OFFENSIVE": {"day_trading": 40, "swing_trading": 40, "position_trading": 20},
    }[directive]
    out = {
        "timestamp": datetime.now().isoformat(),
        "portfolio_directive": directive,
        "confidence": conf,
        "regime": regime,
        "vix": vix,
        "sleeve_tilts_pct": tilts,
        "context_refs": {
            "multi_timeframe_present": bool(sleeves),
            "sector_signal_present": bool(sector),
            "geographic_plan_present": bool(geo),
        },
        "risk_memo": [
            "Keep autonomous paper execution only until 10+ consecutive stable sessions.",
            "Honor volatility-adaptive cap before any discretionary overrides.",
            "Escalate to operator if queue accumulates while RTH remains open.",
        ],
    }
    path = data_dir / f"cio_directive_{datetime.now().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out

