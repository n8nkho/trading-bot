"""Fill-recency entry loosen — bounded relax when Classic has not filled recently."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json

_ROOT = Path(__file__).resolve().parent.parent
_LEDGER = _ROOT / "data" / "pnl_ledger.jsonl"
_OVERRIDES = _ROOT / "data" / "entry_si_overrides.json"
_META = _ROOT / "data" / "last_screening_meta.json"
_FORTRESS_CAPS = Path("/home/ubuntu/fortress-ai/data/si_capability/overrides.json")


def loosen_enabled() -> bool:
    return str(os.environ.get("FORTRESS_CLASSIC_ENTRY_FILL_RECENCY_LOOSEN", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def days_since_last_fill() -> int | None:
    if not _LEDGER.is_file():
        return None
    last_day: str | None = None
    for line in _LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        ts = str(row.get("timestamp") or row.get("ts") or "")[:10]
        if len(ts) >= 10:
            last_day = ts
    if not last_day:
        return None
    try:
        from utils.system_time import now

        d0 = datetime.fromisoformat(last_day).date()
        d1 = now().date()
        return max(0, (d1 - d0).days)
    except Exception:
        return None


def _loosen_days_threshold() -> float:
    raw = os.environ.get("FORTRESS_CLASSIC_FILL_RECENCY_LOOSEN_DAYS", "")
    if raw.strip():
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    if _FORTRESS_CAPS.is_file():
        try:
            doc = json.loads(_FORTRESS_CAPS.read_text(encoding="utf-8"))
            caps = doc.get("capabilities") if isinstance(doc, dict) else {}
            if isinstance(caps, dict) and caps.get("classic_fill_recency_days_max") is not None:
                return max(1.0, float(caps["classic_fill_recency_days_max"]))
        except Exception:
            pass
    return 7.0


def latest_regime() -> str:
    meta = read_json(_META, default={})
    if isinstance(meta, dict):
        return str(meta.get("market_regime_at_screen") or meta.get("market_regime") or "")
    return ""


def load_entry_overrides() -> dict[str, Any]:
    doc = read_json(_OVERRIDES, default={})
    return doc if isinstance(doc, dict) else {}


def loosen_context() -> dict[str, Any]:
    """Return active loosen knobs for entry_agent (empty when inactive)."""
    if not loosen_enabled():
        return {"active": False, "reason": "disabled"}
    days = days_since_last_fill()
    threshold = _loosen_days_threshold()
    if days is None or days < threshold:
        return {
            "active": False,
            "reason": "within_recency_window",
            "days_since_last_fill": days,
            "threshold_days": threshold,
        }
    regime = latest_regime().upper()
    if regime and regime not in ("TRENDING_BULL", "RANGING"):
        return {
            "active": False,
            "reason": f"regime_{regime}",
            "days_since_last_fill": days,
            "threshold_days": threshold,
        }
    ov = load_entry_overrides()
    try:
        rsi_cap = float(
            ov.get("relaxed_rsi_cap")
            or os.environ.get("FORTRESS_CLASSIC_FILL_RECENCY_RSI_CAP", "68")
        )
    except ValueError:
        rsi_cap = 68.0
    try:
        llm_min = float(
            ov.get("llm_min_confidence")
            or os.environ.get("FORTRESS_CLASSIC_FILL_RECENCY_LLM_MIN_CONF", "0.45")
        )
    except ValueError:
        llm_min = 0.45
    try:
        size_mult = float(ov.get("position_size_mult") or "0.65")
    except ValueError:
        size_mult = 0.65
    return {
        "active": True,
        "reason": ov.get("reason") or "fill_recency_gap",
        "days_since_last_fill": days,
        "threshold_days": threshold,
        "regime": regime or None,
        "relaxed_rsi_cap": rsi_cap,
        "llm_min_confidence": llm_min,
        "position_size_mult": max(0.4, min(1.0, size_mult)),
        "markers": ["fill_recency_entry_loosen"],
    }
