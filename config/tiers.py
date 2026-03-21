"""
Tier limits and feature gates — aligned with config/pricing_gates.json.

Lane 1 (personal): use FORTRESS_LICENSE_TIER=master → all gates allowed.
Lanes 2–3 (customers): starter / pro / enterprise from env or license file.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import json
from typing import Any, Dict, FrozenSet, Set

CONFIG_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class TierSpec:
    """Per-tier limits surfaced in health API and for future enforcement."""

    max_universe_size: int


# Explicit caps (tune per product decision). master = practical "unlimited".
_TIER_SPECS: Dict[str, TierSpec] = {
    "starter": TierSpec(max_universe_size=50),
    "pro": TierSpec(max_universe_size=500),
    "enterprise": TierSpec(max_universe_size=10_000),
    "master": TierSpec(max_universe_size=999_999),
}


@lru_cache(maxsize=1)
def _gates_by_tier() -> Dict[str, FrozenSet[str]]:
    """Load tier rows from pricing_gates.json; each tier's gates include inherited names."""
    path = CONFIG_DIR / "pricing_gates.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {
            "starter": frozenset(),
            "pro": frozenset(),
            "enterprise": frozenset(),
            "master": frozenset(),
        }

    tiers: list[dict[str, Any]] = data.get("tiers") or []
    id_to_gates: Dict[str, Set[str]] = {}
    for row in tiers:
        tid = str(row.get("id") or "").strip().lower()
        if not tid:
            continue
        raw_gates = row.get("gates") or []
        id_to_gates[tid] = {str(g).strip().lower() for g in raw_gates if str(g).strip()}

    # Expand: a tier implicitly includes gates of tiers it lists by id in `gates`
    # (e.g. pro lists "starter" → inherit starter's gate tokens).
    def expanded(tier_id: str, seen: Set[str] | None = None) -> Set[str]:
        if seen is None:
            seen = set()
        if tier_id in seen:
            return set()
        seen.add(tier_id)
        base = set(id_to_gates.get(tier_id, set()))
        out = set(base)
        for token in list(base):
            if token in id_to_gates:
                out |= expanded(token, seen)
        return out

    out: Dict[str, FrozenSet[str]] = {}
    for tid in id_to_gates:
        out[tid] = frozenset(expanded(tid))
    # master: all defined gates from all tiers
    all_tokens: Set[str] = set()
    for fs in out.values():
        all_tokens |= set(fs)
    out["master"] = frozenset(all_tokens)
    return out


def _tier_gates(tier: str) -> FrozenSet[str]:
    t = (tier or "").strip().lower()
    m = _gates_by_tier()
    if t in m:
        return m[t]
    return frozenset()


def has_gate(tier: str, gate: str) -> bool:
    """True if this tier includes the given gate token (after pricing_gates expansion)."""
    if (tier or "").strip().lower() == "master":
        return True
    g = (gate or "").strip().lower()
    return g in _tier_gates(tier)


def backtest_allowed(tier: str) -> bool:
    """Walk-forward / backtest style features (Pro+ in pricing_gates: walk_forward_report)."""
    if (tier or "").strip().lower() == "master":
        return True
    return has_gate(tier, "walk_forward_report")


def fortress_allowed(tier: str) -> bool:
    """Fortress hedging and related (Pro+)."""
    if (tier or "").strip().lower() == "master":
        return True
    return has_gate(tier, "fortress_hedging")


def trust_ledger_export_allowed(tier: str) -> bool:
    """Trust ledger export (Pro+)."""
    if (tier or "").strip().lower() == "master":
        return True
    return has_gate(tier, "trust_ledger_export")


def get_tier_spec(tier: str) -> TierSpec:
    t = (tier or "").strip().lower()
    return _TIER_SPECS.get(t, _TIER_SPECS["starter"])
