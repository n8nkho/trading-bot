from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_market_assets() -> dict[str, Any]:
    """
    Centralized instruments/tickers config.

    Goal: keep strategy code free of hard-coded ticker literals by reading them from JSON.
    """
    path = Path("config") / "market_assets.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def require_market_assets() -> dict[str, Any]:
    """
    Same as load_market_assets(), but kept explicit for readability.
    Strategies should treat missing/invalid config as "disabled".
    """
    return load_market_assets()

