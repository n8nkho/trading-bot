"""
Product tiers for customer deployments.

Master = full codebase (your internal version); no restrictions.
Customer tiers (Starter, Pro, Enterprise) are deployed with the same codebase
but restricted by license. Gate features here so deployment is tier-driven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set

# Tier ids must match license.json "tier" and data/license.json
TIER_MASTER = "master"
TIER_STARTER = "starter"
TIER_PRO = "pro"
TIER_ENTERPRISE = "enterprise"

# Strategy ids that can be gated (subset of run_strategies + core agents)
CORE_STRATEGIES = {
    "screener",
    "exit_monitor",
    "risk_guardian",
    "orchestrator",
    "sync_alpaca",
    "intraday_sniper",
    "regime_alignment",
    "universe_builder",
}
EXTENDED_STRATEGIES = {
    "momentum",
    "trump",
    "mergerarb",
    "smartmoney",
    "earnings",
    "insider",
    "squeeze",
    "sector",
    "vwap",
    "flow",
}
EXPERIMENTAL_STRATEGIES = {"forex_sniper", "inefficiency"}


@dataclass
class TierSpec:
    """What a tier allows."""

    tier_id: str
    label: str
    max_universe_size: int
    max_strategies: int  # total strategy slots (core + extended count)
    allowed_strategy_ids: Set[str]  # empty = all from allowed sets
    backtest_allowed: bool
    command_center_allowed: bool
    fortress_hedging_allowed: bool
    auto_trading_allowed: bool
    customer_settings_allowed: bool  # can use bounded risk settings


def _all_strategies() -> Set[str]:
    return CORE_STRATEGIES | EXTENDED_STRATEGIES | EXPERIMENTAL_STRATEGIES


TIER_SPECS = {
    TIER_MASTER: TierSpec(
        tier_id=TIER_MASTER,
        label="Master (internal)",
        max_universe_size=10000,
        max_strategies=999,
        allowed_strategy_ids=set(),  # all
        backtest_allowed=True,
        command_center_allowed=True,
        fortress_hedging_allowed=True,
        auto_trading_allowed=True,
        customer_settings_allowed=True,
    ),
    TIER_STARTER: TierSpec(
        tier_id=TIER_STARTER,
        label="Starter",
        max_universe_size=200,
        max_strategies=len(CORE_STRATEGIES) + 1,  # core + 1 extended
        allowed_strategy_ids=CORE_STRATEGIES | {"momentum"},  # example: 1 extended
        backtest_allowed=False,
        command_center_allowed=True,
        fortress_hedging_allowed=False,
        auto_trading_allowed=True,
        customer_settings_allowed=True,
    ),
    TIER_PRO: TierSpec(
        tier_id=TIER_PRO,
        label="Pro",
        max_universe_size=1000,
        max_strategies=len(CORE_STRATEGIES) + len(EXTENDED_STRATEGIES),
        allowed_strategy_ids=CORE_STRATEGIES | EXTENDED_STRATEGIES,
        backtest_allowed=True,
        command_center_allowed=True,
        fortress_hedging_allowed=True,
        auto_trading_allowed=True,
        customer_settings_allowed=True,
    ),
    TIER_ENTERPRISE: TierSpec(
        tier_id=TIER_ENTERPRISE,
        label="Enterprise",
        max_universe_size=5000,
        max_strategies=999,
        allowed_strategy_ids=set(),  # all
        backtest_allowed=True,
        command_center_allowed=True,
        fortress_hedging_allowed=True,
        auto_trading_allowed=True,
        customer_settings_allowed=True,
    ),
}


def get_tier_spec(tier_id: str | None) -> TierSpec:
    """Return spec for tier; unknown tier defaults to Starter (restrictive)."""
    if not tier_id:
        return TIER_SPECS[TIER_STARTER]
    spec = TIER_SPECS.get(tier_id)
    if spec is None:
        return TIER_SPECS[TIER_STARTER]
    return spec


def strategy_allowed(strategy_id: str, tier_id: str | None) -> bool:
    """True if this strategy is allowed for the given tier."""
    spec = get_tier_spec(tier_id)
    if not spec.allowed_strategy_ids:
        return True
    return strategy_id in spec.allowed_strategy_ids


def backtest_allowed(tier_id: str | None) -> bool:
    return get_tier_spec(tier_id).backtest_allowed


def command_center_allowed(tier_id: str | None) -> bool:
    return get_tier_spec(tier_id).command_center_allowed


def fortress_allowed(tier_id: str | None) -> bool:
    return get_tier_spec(tier_id).fortress_hedging_allowed


def customer_settings_allowed(tier_id: str | None) -> bool:
    return get_tier_spec(tier_id).customer_settings_allowed


def max_universe_for_tier(tier_id: str | None) -> int:
    return get_tier_spec(tier_id).max_universe_size
