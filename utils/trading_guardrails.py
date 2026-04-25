"""
Supplemental safety guardrails shared across runtime agents.

Designed to be fail-safe and low-coupling:
- all checks degrade gracefully when data is unavailable
- enforcement can be toggled independently from observation
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "guardrail_runtime_state.json"

VALID_TICKER_PATTERN = re.compile(r"^[A-Z]{1,5}$")


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _read_state() -> dict[str, Any]:
    try:
        if _STATE_PATH.exists():
            doc = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return doc
    except Exception:
        pass
    return {}


def _write_state(doc: dict[str, Any]) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    except Exception:
        pass


def update_equity_state(current_equity: float | None) -> dict[str, Any]:
    """
    Track equity history for drawdown/daily-loss/velocity checks.
    Returns a compact computed snapshot.
    """
    now = datetime.now()
    eq = _safe_float(current_equity)
    state = _read_state()
    history = state.get("equity_samples")
    if not isinstance(history, list):
        history = []

    # keep only ~35 days
    min_ts = now - timedelta(days=35)
    pruned: list[dict[str, Any]] = []
    for row in history:
        try:
            ts = datetime.fromisoformat(str(row.get("ts")))
            val = _safe_float(row.get("equity"))
            if val is None or ts < min_ts:
                continue
            pruned.append({"ts": ts.isoformat(), "equity": val})
        except Exception:
            continue

    if eq is not None and eq > 0:
        pruned.append({"ts": now.isoformat(), "equity": eq})

    # keep bounded list
    pruned = pruned[-5000:]
    state["equity_samples"] = pruned
    _write_state(state)

    def _max_in_window(days: int) -> float | None:
        cutoff = now - timedelta(days=days)
        vals = []
        for row in pruned:
            try:
                ts = datetime.fromisoformat(str(row.get("ts")))
                if ts >= cutoff:
                    v = _safe_float(row.get("equity"))
                    if v is not None:
                        vals.append(v)
            except Exception:
                continue
        return max(vals) if vals else None

    def _first_for_day() -> float | None:
        day = now.date()
        vals = []
        for row in pruned:
            try:
                ts = datetime.fromisoformat(str(row.get("ts")))
                if ts.date() == day:
                    v = _safe_float(row.get("equity"))
                    if v is not None:
                        vals.append((ts, v))
            except Exception:
                continue
        if not vals:
            return None
        vals.sort(key=lambda t: t[0])
        return vals[0][1]

    def _sample_hours_ago(hours: float) -> float | None:
        target = now - timedelta(hours=float(hours))
        nearest: tuple[float, float] | None = None
        for row in pruned:
            try:
                ts = datetime.fromisoformat(str(row.get("ts")))
                v = _safe_float(row.get("equity"))
                if v is None:
                    continue
                delta = abs((ts - target).total_seconds())
                if nearest is None or delta < nearest[0]:
                    nearest = (delta, v)
            except Exception:
                continue
        return nearest[1] if nearest else None

    return {
        "current_equity": eq,
        "peak_30d_equity": _max_in_window(30),
        "daily_start_equity": _first_for_day(),
        "equity_1h_ago": _sample_hours_ago(1.0),
    }


def compute_loss_metrics(equity_snapshot: dict[str, Any]) -> dict[str, float | None]:
    cur = _safe_float(equity_snapshot.get("current_equity"))
    peak = _safe_float(equity_snapshot.get("peak_30d_equity"))
    day0 = _safe_float(equity_snapshot.get("daily_start_equity"))
    h1 = _safe_float(equity_snapshot.get("equity_1h_ago"))

    drawdown = None
    if cur is not None and peak and peak > 0:
        drawdown = max(0.0, (peak - cur) / peak)

    daily_loss = None
    if cur is not None and day0 and day0 > 0:
        daily_loss = max(0.0, (day0 - cur) / day0)

    velocity = None
    if cur is not None and h1 and cur > 0:
        velocity = abs((cur - h1) / cur)

    return {
        "drawdown_from_peak": drawdown,
        "daily_loss_pct": daily_loss,
        "hourly_equity_velocity": velocity,
    }


def validate_llm_trade_output(ticker: str, reasoning: str) -> tuple[bool, str]:
    """
    Lightweight hallucination checks for LLM-generated intents.
    """
    t = str(ticker or "").strip().upper()
    if not VALID_TICKER_PATTERN.match(t):
        return False, "hallucinated_ticker_format"

    low = str(reasoning or "").lower()
    if "strong buy" in low and "avoid" in low:
        return False, "contradictory_reasoning"

    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", str(reasoning or ""))
    for raw in nums:
        try:
            v = float(raw)
            if abs(v) > 10_000:
                return False, "implausible_metric_value"
        except Exception:
            continue

    return True, "ok"


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}
