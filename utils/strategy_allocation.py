from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ALLOC_PATH = _ROOT / "config" / "strategy_allocation.yaml"


class SleeveRiskConfig(BaseModel):
    max_position_size_pct: float = 3.0
    max_total_risk_pct: float = 7.0
    max_open_positions: int = 5
    stop_loss_pct: float = -2.0
    take_profit_pct: float = 5.0


class SleeveActivationConfig(BaseModel):
    min_vix: float | None = None
    max_vix: float | None = None
    allowed_regimes: list[str] = Field(default_factory=list)


class SleeveConfig(BaseModel):
    name: str
    capital_allocation_pct: float
    holding_period: str
    enabled: bool = True
    risk: SleeveRiskConfig = Field(default_factory=SleeveRiskConfig)
    activation: SleeveActivationConfig = Field(default_factory=SleeveActivationConfig)


class StrategyAllocationConfig(BaseModel):
    version: int = 1
    default_currency: str = "USD"
    sleeves: dict[str, SleeveConfig]

    @model_validator(mode="after")
    def _validate_total_allocation(self) -> "StrategyAllocationConfig":
        total = sum(s.capital_allocation_pct for s in self.sleeves.values())
        # Allow tiny float drift around 100.
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"sleeves capital_allocation_pct must total 100.0, got {total}")
        return self


def load_strategy_allocation_config(path: Path | None = None) -> StrategyAllocationConfig:
    cfg_path = path or _DEFAULT_ALLOC_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"strategy allocation config not found: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        raw: Any = yaml.safe_load(f) or {}
    return StrategyAllocationConfig.model_validate(raw)

