"""Append-only closed trade history for reflection agent (atomic updates)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json, write_json_atomic

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "trade_history.json"
_EMPTY = {"trades": []}


def _load() -> dict[str, Any]:
    doc = read_json(_PATH, _EMPTY)
    if not isinstance(doc, dict):
        return dict(_EMPTY)
    trades = doc.get("trades")
    if not isinstance(trades, list):
        doc["trades"] = []
    return doc


def _to_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_pnl_fields(record: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure percentage PnL fields are consistently present for downstream reflection.

    Canonical field is `pnl_pct` in percent units, e.g. 2.5 means +2.5%.
    """
    out = dict(record)
    pct = _to_float(out.get("pnl_pct"))
    if pct is None:
        pct = _to_float(out.get("pnl_percent"))
    if pct is None:
        pct = _to_float(out.get("return_pct"))
    if pct is None:
        frac = _to_float(out.get("pnl_pct_fraction"))
        if frac is not None:
            # Fractional inputs are common in orchestrator, e.g. 0.023 => 2.3%.
            pct = frac * 100.0 if abs(frac) <= 1.0 else frac
    if pct is not None:
        out["pnl_pct"] = round(pct, 6)
    return out


def append_closed_trade(record: dict[str, Any]) -> str:
    tid = str(record.get("id") or uuid.uuid4())
    record = _normalize_pnl_fields(dict(record))
    record.setdefault("id", tid)
    doc = _load()
    doc["trades"].append(record)
    write_json_atomic(_PATH, doc)
    return tid
