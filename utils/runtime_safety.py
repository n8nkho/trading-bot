"""Operator-visible runtime safety flags (hedge execution failures, etc.)."""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json, write_json_atomic

_ROOT = Path(__file__).resolve().parent.parent
PATH = _ROOT / "data" / "runtime_safety.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _utc(),
        "hedging_execution_error": {
            "active": False,
            "since": None,
            "detail": None,
            "traceback_excerpt": None,
        },
    }


def read_state() -> dict[str, Any]:
    doc = read_json(PATH, default={})
    if not isinstance(doc, dict):
        doc = {}
    base = default_state()
    hed = doc.get("hedging_execution_error")
    if isinstance(hed, dict):
        base["hedging_execution_error"].update(hed)
    base["updated_at"] = doc.get("updated_at") or base["updated_at"]
    return base


def set_hedging_error(exc: BaseException | None, *, detail: str | None = None) -> dict[str, Any]:
    st = read_state()
    tb = traceback.format_exc()[:8000] if exc is not None else None
    st["hedging_execution_error"] = {
        "active": True,
        "since": _utc(),
        "detail": detail or (str(exc) if exc else "unknown"),
        "traceback_excerpt": tb,
    }
    st["updated_at"] = _utc()
    PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(PATH, st)
    return st


def clear_hedging_error() -> dict[str, Any]:
    st = read_state()
    st["hedging_execution_error"] = {
        "active": False,
        "since": None,
        "detail": None,
        "traceback_excerpt": None,
        "cleared_at": _utc(),
    }
    st["updated_at"] = _utc()
    write_json_atomic(PATH, st)
    return st


def hedging_error_blocks_entries() -> tuple[bool, str]:
    if (_ROOT / "data" / "hedge_error_cleared.flag").exists():
        return False, "operator_cleared_flag_file"
    enforce = __import__("os").getenv("FORTRESS_HEDGE_ERROR_BLOCK_ENTRIES", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    st = read_state().get("hedging_execution_error") or {}
    active = bool(st.get("active"))
    if enforce and active:
        return True, str(st.get("detail") or "hedging_execution_error")
    return False, ""
