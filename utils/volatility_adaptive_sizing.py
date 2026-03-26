from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VolatilitySizingTier:
    name: str
    min_vix: float
    max_vix: float | None
    max_position_size_pct: float
    mode: str


TIERS: tuple[VolatilitySizingTier, ...] = (
    VolatilitySizingTier("conservative", min_vix=0.0, max_vix=15.0, max_position_size_pct=2.0, mode="momentum"),
    VolatilitySizingTier("normal", min_vix=15.0, max_vix=25.0, max_position_size_pct=3.0, mode="balanced"),
    VolatilitySizingTier("aggressive", min_vix=25.0, max_vix=35.0, max_position_size_pct=4.0, mode="mean_reversion"),
    VolatilitySizingTier("maximum_opportunity", min_vix=35.0, max_vix=None, max_position_size_pct=5.0, mode="crisis_alpha"),
)


def resolve_tier(vix: float | None) -> VolatilitySizingTier:
    if vix is None:
        return TIERS[1]  # normal
    for t in TIERS:
        hi = float("inf") if t.max_vix is None else t.max_vix
        if t.min_vix <= vix < hi:
            return t
    return TIERS[-1]


def load_latest_vix_from_fortress_report(data_dir: Path | None = None) -> float | None:
    root = data_dir or Path("data")
    files = sorted(glob.glob(str(root / "fortress_report_*.json")), reverse=True)
    if not files:
        return None
    try:
        doc = json.loads(Path(files[0]).read_text(encoding="utf-8"))
        mc = doc.get("market_conditions") if isinstance(doc, dict) else {}
        raw = mc.get("vix") if isinstance(mc, dict) else None
        return float(raw) if raw is not None else None
    except Exception:
        return None


def adaptive_position_size_pct(
    *,
    base_position_size_pct: float,
    vix: float | None,
) -> tuple[float, VolatilitySizingTier]:
    """
    Counter-cyclical sizing: higher VIX -> larger max position size cap.
    Output is bounded by max(base, tier_cap) to avoid reducing below configured base.
    """
    tier = resolve_tier(vix)
    out = max(float(base_position_size_pct), float(tier.max_position_size_pct))
    return out, tier

