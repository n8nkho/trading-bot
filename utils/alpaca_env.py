"""
Shared Alpaca environment helpers (paper vs live from ALPACA_BASE_URL).
"""
from __future__ import annotations

import os


def is_alpaca_paper() -> bool:
    """
    True when ALPACA_BASE_URL is unset, empty, or contains 'paper'.
    False for typical live URL (e.g. https://api.alpaca.markets).
    """
    base = (os.getenv("ALPACA_BASE_URL") or "").strip().lower()
    if not base:
        return True
    return "paper" in base
