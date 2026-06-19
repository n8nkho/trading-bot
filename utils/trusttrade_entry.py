"""
TrustTrade-lite for Classic entry — selective two-pass consensus + screener context.

Runs critique_loop only on borderline setups; high L2 skips LLM debate (CATTS-lite).
Fused anchor veto lives in fused_signal_model.apply_fused_entry_gates.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _ROOT / "config" / "trusttrade_entry.yaml"


def enabled() -> bool:
    return str(os.environ.get("FORTRESS_TRUSTTRADE_ENTRY", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def config_path() -> Path:
    raw = (os.environ.get("FORTRESS_TRUSTTRADE_CONFIG_PATH") or "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_CONFIG


def load_config() -> dict[str, float]:
    defaults = {
        "l2_borderline_lo": 60.0,
        "l2_borderline_hi": 75.0,
        "l2_strong_min": 75.0,
        "fused_borderline_lo": -0.10,
        "fused_borderline_hi": 0.15,
        "fused_strong_min": 0.25,
        "l2_veto_bypass_min": 75.0,
    }
    path = config_path()
    if not path.is_file():
        return defaults
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict):
            return defaults
        out = dict(defaults)
        for key in defaults:
            if doc.get(key) is not None:
                out[key] = float(doc[key])
        return out
    except Exception:
        return defaults


def layer2_score_from_candidate(candidate: dict[str, Any] | None) -> float | None:
    if not isinstance(candidate, dict):
        return None
    rs = candidate.get("recursive_screener")
    if not isinstance(rs, dict):
        return None
    try:
        return float(rs.get("layer2_score"))
    except (TypeError, ValueError):
        return None


def _fused_score_from_decision(decision: dict[str, Any]) -> float | None:
    adv = decision.get("fused_signal_advisory")
    if isinstance(adv, dict) and adv.get("fused_score") is not None:
        try:
            return float(adv["fused_score"])
        except (TypeError, ValueError):
            pass
    if decision.get("fused_score") is not None:
        try:
            return float(decision["fused_score"])
        except (TypeError, ValueError):
            pass
    return None


def attach_screener_context(decision: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Copy recursive screener fields onto entry decision for audit / critique gating."""
    if not isinstance(decision, dict) or not isinstance(candidate, dict):
        return decision
    l2 = layer2_score_from_candidate(candidate)
    if l2 is not None:
        decision["layer2_score"] = round(l2, 2)
    rs = candidate.get("recursive_screener")
    if isinstance(rs, dict):
        decision["recursive_screener"] = rs
    return decision


def critique_consensus_needed(decision: dict[str, Any]) -> tuple[bool, str]:
    """
    Return (needs_two_pass_critique, reason_code).

    When TrustTrade is disabled, always require critique (legacy behavior when critique_loop on).
    """
    if not enabled():
        return True, "trusttrade_disabled"

    cfg = load_config()
    l2_raw = decision.get("layer2_score")
    l2: float | None
    try:
        l2 = float(l2_raw) if l2_raw is not None else None
    except (TypeError, ValueError):
        l2 = None

    fused = _fused_score_from_decision(decision)
    border_lo = cfg["l2_borderline_lo"]
    border_hi = cfg["l2_borderline_hi"]
    strong_l2 = cfg["l2_strong_min"]
    fused_lo = cfg["fused_borderline_lo"]
    fused_hi = cfg["fused_borderline_hi"]
    fused_strong = cfg["fused_strong_min"]

    if l2 is not None and l2 >= strong_l2:
        if fused is not None and fused_lo < fused <= fused_hi:
            return True, "borderline_fused_consensus"
        return False, "high_l2_skip_critique"

    if l2 is not None and border_lo <= l2 < border_hi:
        return True, "borderline_l2_consensus"

    if l2 is not None and l2 < border_lo:
        return True, "low_l2_consensus"

    if fused is not None:
        if fused <= fused_lo:
            return True, "weak_fused_consensus"
        if fused_lo < fused <= fused_hi:
            return True, "borderline_fused_consensus"
        if fused >= fused_strong:
            return False, "strong_fused_skip_critique"

    if l2 is None:
        return True, "missing_l2_consensus"

    return False, "default_skip_critique"


def l2_veto_bypass_min() -> float:
    return load_config()["l2_veto_bypass_min"]


def should_bypass_fused_veto(decision: dict[str, Any]) -> tuple[bool, str]:
    """TrustTrade: high recursive L2 overrides macro fused veto."""
    if not isinstance(decision, dict) or decision.get("action") != "BUY":
        return False, ""
    l2_raw = decision.get("layer2_score")
    try:
        l2 = float(l2_raw) if l2_raw is not None else None
    except (TypeError, ValueError):
        l2 = None
    if l2 is not None and l2 >= l2_veto_bypass_min():
        return True, "high_l2_fused_veto_bypass"
    return False, ""
