"""
Persistent trailing-stop state for stock exits (survives Alpaca sync).

Stored in data/exit_trailing_state.json — keyed by ticker.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "exit_trailing_state.json"


def _load() -> dict[str, Any]:
    if not _PATH.exists():
        return {}
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception as e:
        logger.warning("exit_trailing_state read failed: %s", e)
        return {}


def _save(data: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def get_state(ticker: str) -> dict[str, Any]:
    sym = str(ticker or "").strip().upper()
    if not sym:
        return {}
    st = _load().get(sym)
    return dict(st) if isinstance(st, dict) else {}


def update_peak(ticker: str, current_price: float) -> None:
    """Raise peak to max(peak, current_price) while trailing is active."""
    sym = str(ticker or "").strip().upper()
    if not sym:
        return
    data = _load()
    row = dict(data.get(sym) or {})
    if not row.get("active"):
        return
    peak = float(row.get("peak") or 0.0)
    cp = float(current_price)
    if cp > peak:
        row["peak"] = cp
        data[sym] = row
        _save(data)


def activate_after_tier1(ticker: str, fill_price: float) -> None:
    """Call after first take-profit tier1 partial sell — start trailing from fill price."""
    sym = str(ticker or "").strip().upper()
    if not sym:
        return
    data = _load()
    fp = float(fill_price)
    data[sym] = {
        "active": True,
        "peak": fp,
        "activated_at": datetime.now().isoformat(),
    }
    _save(data)
    logger.info("Trailing stop activated for %s peak=%.4f", sym, fp)


def clear(ticker: str) -> None:
    sym = str(ticker or "").strip().upper()
    if not sym:
        return
    data = _load()
    if sym in data:
        del data[sym]
        _save(data)
