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


def append_closed_trade(record: dict[str, Any]) -> str:
    tid = str(record.get("id") or uuid.uuid4())
    record = dict(record)
    record.setdefault("id", tid)
    doc = _load()
    doc["trades"].append(record)
    write_json_atomic(_PATH, doc)
    return tid
