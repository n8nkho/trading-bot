"""Adaptive RSI alignment — screener prefilter must not lag entry SI ceiling."""
from __future__ import annotations

from typing import Any

from utils.atomic_json import read_json

_META = __import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "last_screening_meta.json"
_ENTRY_OV = __import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "entry_si_overrides.json"


def scan_adaptive_rsi_screener_drift() -> list[dict[str, Any]]:
    """
    Detect when entry fill-recency RSI is relaxed but last screener run used a tighter prefilter.
    """
    meta = read_json(_META, default={})
    if not isinstance(meta, dict) or not meta:
        return []

    adaptive = meta.get("adaptive_rsi") if isinstance(meta.get("adaptive_rsi"), dict) else {}
    ceiling = adaptive.get("ceiling")
    if ceiling is None:
        try:
            from utils.adaptive_rsi import adaptive_rsi_ceiling

            ceiling = adaptive_rsi_ceiling()
        except Exception:
            return []

    try:
        ceiling_f = float(ceiling)
    except (TypeError, ValueError):
        return []

    ov = read_json(_ENTRY_OV, default={})
    if not (isinstance(ov, dict) and ov.get("active")):
        return []

    relaxed = float(ov.get("relaxed_rsi_cap") or ceiling_f)
    if relaxed <= 45:
        return []

    # Inspect reject samples for tight lt_* rules well below adaptive ceiling.
    samples = meta.get("prefilter_reject_samples") or []
    if not isinstance(samples, list):
        samples = []
    tight_rsi_rejects = 0
    for s in samples[:30]:
        if not isinstance(s, dict):
            continue
        if s.get("reason") != "rsi_criteria":
            continue
        rule = str(s.get("rsi_rule") or "")
        if rule.startswith("lt_"):
            try:
                thr = float(rule.split("_", 1)[1])
            except (IndexError, ValueError):
                continue
            if thr + 8 < min(relaxed, ceiling_f):
                tight_rsi_rejects += 1

    if tight_rsi_rejects < 3:
        return []

    return [
        {
            "code": "adaptive_rsi_screener_drift",
            "severity": "high",
            "component": "screener_agent",
            "adaptive_ceiling": round(ceiling_f, 1),
            "entry_relaxed_rsi_cap": round(relaxed, 1),
            "tight_rsi_reject_samples": tight_rsi_rejects,
            "market_regime": meta.get("market_regime_at_screen"),
            "recommendation": (
                "Screener RSI prefilter is tighter than adaptive entry ceiling — "
                "wire utils/adaptive_rsi into screener tiers (Classic throughput bottleneck)."
            ),
            "si_action": "align_adaptive_rsi_screener",
            "mitigation_markers": ["adaptive_rsi", "fill_recency_entry_loosen"],
        }
    ]
