from __future__ import annotations

"""
License / plan scaffolding.

Reads an optional data/license.json file describing the current plan.
When missing, defaults to a generous single-tenant dev plan so that
existing behavior is unchanged.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LICENSE_FILE = PROJECT_ROOT / "data" / "license.json"


@dataclass
class Plan:
    name: str = "dev-unlimited"
    max_tenants: int = 1
    max_strategies: int = 999
    max_universe_size: int = 10000
    auto_trading_allowed: bool = True


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        return {}
    return {}


def get_plan() -> Plan:
    data = _read_json(LICENSE_FILE)
    if not data:
        return Plan()
    return Plan(
        name=str(data.get("name", "dev-unlimited")),
        max_tenants=int(data.get("max_tenants", 1)),
        max_strategies=int(data.get("max_strategies", 999)),
        max_universe_size=int(data.get("max_universe_size", 10000)),
        auto_trading_allowed=bool(data.get("auto_trading_allowed", True)),
    )


