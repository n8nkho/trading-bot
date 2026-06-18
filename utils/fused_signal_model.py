"""
Composite fused signal score from parallel intelligence artifacts.

Read-only consumers of existing JSON producers — does not modify their writers.
Default off: FORTRESS_FUSED_SIGNAL_ENABLED=0, FORTRESS_FUSED_SIGNAL_AFFECTS_ENTRY=0.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_DEFAULT_WEIGHTS = _ROOT / "config" / "fused_signal_weights.yaml"
_OUT = _DATA / "fused_signal_score.json"

_REGIME_SCORE = {
    "TRENDING_BULL": 0.85,
    "TRENDING_BEAR": -0.85,
    "RANGING": 0.0,
    "VOLATILE": -0.35,
    "CRISIS": -1.0,
}


def _enabled() -> bool:
    return str(os.environ.get("FORTRESS_FUSED_SIGNAL_ENABLED", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def affects_entry() -> bool:
    return str(os.environ.get("FORTRESS_FUSED_SIGNAL_AFFECTS_ENTRY", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _halted() -> bool:
    try:
        from utils.operator_halt import is_trading_halted

        return bool(is_trading_halted())
    except Exception:
        return str(os.environ.get("FORTRESS_TRADING_HALT", "")).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )


def weights_path() -> Path:
    raw = (os.environ.get("FORTRESS_FUSED_SIGNAL_WEIGHTS_PATH") or "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_WEIGHTS


def load_weights() -> dict[str, float]:
    path = weights_path()
    if not path.is_file():
        return {k: 0.2 for k in _REGIME_SCORE}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        comps = doc.get("components") if isinstance(doc, dict) else {}
        if not isinstance(comps, dict):
            comps = {}
        out = {str(k): float(v) for k, v in comps.items()}
        total = sum(abs(x) for x in out.values()) or 1.0
        return {k: v / total for k, v in out.items()}
    except Exception:
        return {k: 0.2 for k in ("regime", "sentiment_velocity", "options_flow", "earnings_intel", "cross_asset")}


def max_confidence_delta() -> float:
    path = weights_path()
    try:
        if path.is_file():
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(doc, dict) and doc.get("max_confidence_delta") is not None:
                return max(0.0, min(0.15, float(doc["max_confidence_delta"])))
    except Exception:
        pass
    return 0.05


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _component_regime() -> tuple[float, dict[str, Any]]:
    doc = _read_json(_DATA / "daily_risk_params.json", {})
    regime = str((doc or {}).get("regime") or "RANGING").upper()
    conf = float((doc or {}).get("regime_confidence") or 0.5)
    raw = _REGIME_SCORE.get(regime, 0.0) * conf
    return raw, {"regime": regime, "regime_confidence": conf}


def _component_sentiment(symbol: str) -> tuple[float, dict[str, Any]]:
    doc = _read_json(_DATA / "sentiment_velocity.json", {})
    sym = symbol.upper()
    row = (doc.get("symbols") or {}).get(sym) if isinstance(doc, dict) else None
    if not isinstance(row, dict):
        return 0.0, {"symbol": sym, "signal": "MISSING"}
    vel = float(row.get("velocity") or 0.0)
    score = max(-1.0, min(1.0, vel * 4.0))
    return score, {"velocity": vel, "classification": row.get("classification"), "signal": row.get("signal")}


def _component_options_flow(symbol: str) -> tuple[float, dict[str, Any]]:
    doc = _read_json(_DATA / "options_flow.json", {})
    sym = symbol.upper()
    signals = doc.get("signals") if isinstance(doc, dict) else []
    best = 0.0
    picked: dict[str, Any] = {}
    if isinstance(signals, list):
        for sig in signals:
            if not isinstance(sig, dict) or str(sig.get("symbol") or "").upper() != sym:
                continue
            sc = sig.get("score") if isinstance(sig.get("score"), dict) else {}
            direction = str(sc.get("direction") or "NEUTRAL").upper()
            conv = float(sc.get("conviction") or 0.0) / 10.0
            val = conv if direction == "BULL" else (-conv if direction == "BEAR" else 0.0)
            if abs(val) >= abs(best):
                best = val
                picked = {"classification": sig.get("classification"), "direction": direction, "conviction": sc.get("conviction")}
    return max(-1.0, min(1.0, best)), picked or {"symbol": sym, "signal": "MISSING"}


def _component_earnings(symbol: str) -> tuple[float, dict[str, Any]]:
    doc = _read_json(_DATA / "earnings_intel.json", {"entries": []})
    sym = symbol.upper()
    entries = doc.get("entries") if isinstance(doc, dict) else []
    action = ""
    verdict = ""
    if isinstance(entries, list):
        for row in entries:
            if not isinstance(row, dict) or str(row.get("symbol") or "").upper() != sym:
                continue
            analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
            inner = analysis.get("analysis") if isinstance(analysis.get("analysis"), dict) else analysis
            action = str(inner.get("recommended_action") or inner.get("overall_verdict") or "").upper()
            verdict = str(inner.get("overall_verdict") or "")
            break
    bullish = {"BUY", "OVERWEIGHT", "ACCUMULATE", "POSITIVE", "BEAT"}
    bearish = {"SELL", "UNDERWEIGHT", "REDUCE", "NEGATIVE", "MISS"}
    if any(x in action for x in bullish) or verdict in bullish:
        return 0.6, {"recommended_action": action, "overall_verdict": verdict}
    if any(x in action for x in bearish) or verdict in bearish:
        return -0.6, {"recommended_action": action, "overall_verdict": verdict}
    return 0.0, {"recommended_action": action or "NEUTRAL", "overall_verdict": verdict}


def _component_cross_asset() -> tuple[float, dict[str, Any]]:
    doc = _read_json(_DATA / "cross_asset_signal.json", {})
    bias = str((doc or {}).get("overall_bias") or "NEUTRAL").upper()
    conf = float((doc or {}).get("confidence") or 0) / 10.0
    mapping = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}
    raw = mapping.get(bias, 0.0) * max(0.0, min(1.0, conf))
    return max(-1.0, min(1.0, raw)), {"overall_bias": bias, "confidence": (doc or {}).get("confidence")}


def compute_symbol_score(symbol: str, *, weights: dict[str, float] | None = None) -> dict[str, Any]:
    """Return fused score in [-1, 1] plus auditable component breakdown."""
    w = weights or load_weights()
    sym = str(symbol or "").strip().upper()
    parts: dict[str, Any] = {}

    r_val, r_meta = _component_regime()
    parts["regime"] = {"value": round(r_val, 4), "inputs": r_meta, "weight": w.get("regime", 0.2)}

    s_val, s_meta = _component_sentiment(sym)
    parts["sentiment_velocity"] = {"value": round(s_val, 4), "inputs": s_meta, "weight": w.get("sentiment_velocity", 0.2)}

    o_val, o_meta = _component_options_flow(sym)
    parts["options_flow"] = {"value": round(o_val, 4), "inputs": o_meta, "weight": w.get("options_flow", 0.2)}

    e_val, e_meta = _component_earnings(sym)
    parts["earnings_intel"] = {"value": round(e_val, 4), "inputs": e_meta, "weight": w.get("earnings_intel", 0.2)}

    c_val, c_meta = _component_cross_asset()
    parts["cross_asset"] = {"value": round(c_val, 4), "inputs": c_meta, "weight": w.get("cross_asset", 0.2)}

    score = 0.0
    for key, block in parts.items():
        wt = float(block.get("weight") or 0.0)
        score += wt * float(block.get("value") or 0.0)
    score = max(-1.0, min(1.0, score))

    from utils.system_time import now_iso

    return {
        "symbol": sym,
        "fused_score": round(score, 4),
        "components": parts,
        "ts": now_iso(),
    }


def write_fused_scores(symbols: list[str]) -> dict[str, Any]:
    """Persist per-symbol scores for audit / evolve reweighting."""
    if _halted():
        return {"ok": False, "skipped": "trading_halted"}
    if not _enabled() and not affects_entry():
        return {"ok": False, "skipped": "fused_signal_disabled"}

    weights = load_weights()
    rows = [compute_symbol_score(s, weights=weights) for s in symbols if s]
    from utils.system_time import now_iso

    doc = {
        "version": 1,
        "ts": now_iso(),
        "weights": weights,
        "symbols": {r["symbol"]: r for r in rows},
    }
    _DATA.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(_OUT), "count": len(rows)}


def apply_fused_signal_advisory(
    decision: dict[str, Any],
    *,
    fused_row: dict[str, Any] | None,
    logger: Any | None = None,
) -> dict[str, Any]:
    """Log advisory; optionally nudge confidence when FORTRESS_FUSED_SIGNAL_AFFECTS_ENTRY=1."""
    if _halted() or not _enabled():
        return decision
    if not isinstance(decision, dict):
        return decision
    row = fused_row or {}
    score = row.get("fused_score")
    if score is None:
        return decision

    advisory = {
        "fused_score": score,
        "components": row.get("components"),
        "mode": "log_only",
    }
    if affects_entry() and decision.get("action") == "BUY":
        try:
            conf = float(decision.get("confidence") or 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        delta_cap = max_confidence_delta()
        delta = max(-delta_cap, min(delta_cap, float(score) * delta_cap))
        new_conf = max(0.0, min(1.0, conf + delta))
        decision["confidence"] = new_conf
        advisory["mode"] = "confidence_nudge"
        advisory["confidence_delta"] = round(delta, 4)
        advisory["confidence_before"] = conf
        advisory["confidence_after"] = new_conf
    decision["fused_signal_advisory"] = advisory
    if logger is not None:
        logger.info(
            "%s: fused_signal score=%s mode=%s",
            decision.get("ticker"),
            score,
            advisory.get("mode"),
        )
    return decision


def propose_weight_tuning_from_ledger(*, min_trades: int = 20) -> dict[str, Any] | None:
    """
    Compare ledger outcomes vs stored fused scores; queue proposed weight changes (never silent apply).
    """
    if _halted():
        return None
    if str(os.environ.get("FORTRESS_FUSED_SIGNAL_REWEIGHT", "0")).strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return None

    ledger = _DATA / "pnl_ledger.jsonl"
    scores_doc = _read_json(_OUT, {})
    sym_scores = scores_doc.get("symbols") if isinstance(scores_doc, dict) else {}
    if not isinstance(sym_scores, dict) or not sym_scores:
        return None

    wins_high = losses_high = wins_low = losses_low = 0
    for line in ledger.read_text(encoding="utf-8").splitlines() if ledger.is_file() else []:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        sym = str(rec.get("symbol") or rec.get("ticker") or "").upper()
        try:
            pnl = float(rec.get("pnl"))
        except (TypeError, ValueError):
            continue
        row = sym_scores.get(sym) if isinstance(sym_scores.get(sym), dict) else {}
        try:
            fs = float(row.get("fused_score"))
        except (TypeError, ValueError):
            continue
        bucket = "high" if fs >= 0.25 else ("low" if fs <= -0.25 else "mid")
        if bucket == "mid":
            continue
        if pnl > 0:
            if bucket == "high":
                wins_high += 1
            else:
                wins_low += 1
        elif pnl < 0:
            if bucket == "high":
                losses_high += 1
            else:
                losses_low += 1

    n = wins_high + losses_high + wins_low + losses_low
    if n < min_trades:
        return None

    high_wr = wins_high / max(1, wins_high + losses_high)
    low_wr = wins_low / max(1, wins_low + losses_low)
    if high_wr <= low_wr + 0.05:
        return None

    weights = load_weights()
    proposed = dict(weights)
    for k in list(proposed.keys()):
        proposed[k] = round(float(proposed[k]) * 1.05, 4)
    total = sum(proposed.values()) or 1.0
    proposed = {k: round(v / total, 4) for k, v in proposed.items()}

    return {
        "code": "fused_signal_weight_tune",
        "severity": "medium",
        "component": "classic_fortress",
        "title": "Fused signal weights — ledger suggests upward nudge",
        "recommendation": (
            f"High fused-score bucket win_rate={high_wr:.2f} vs low={low_wr:.2f} over {n} trades. "
            f"Proposed weights: {proposed}. Requires human review before writing YAML."
        ),
        "kind": "tunable",
        "effort": "low",
        "impact": "medium",
        "proposed_weights": proposed,
        "current_weights": weights,
        "sample_trades": n,
    }
