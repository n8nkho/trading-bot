"""
Recursive evolution engine for paper-trading continuous improvement.

Phases implemented:
1) Self-diagnosis and fix proposals
2) Parameter auto-tuning proposals
3) Strategy A/B allocation via Thompson sampling
4) Autonomous change plan (safe-by-default; write-apply gated by env)
5) Meta-learning update loop
"""

from __future__ import annotations

import glob
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.risk_guardian import get_risk_status
from agents.llm_reasoning_engine import LLMReasoningEngine
from agents.llm_learning_agent import LLMLearningAgent
from utils.local_llm import call_llm


DATA_DIR = Path("data")
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("recursive_evolution")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _fh = logging.FileHandler(LOG_DIR / "evolution.log")
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(_fh)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _latest_json(pattern: str) -> dict[str, Any]:
    try:
        files = sorted(glob.glob(str(DATA_DIR / pattern)), reverse=True)
        if not files:
            return {}
        doc = _read_json(Path(files[0]), {})
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _read_jsonl(path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        if not path.exists():
            return rows
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
                if len(rows) >= limit:
                    break
    except Exception:
        pass
    return rows


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _beta_sample(alpha: float, beta: float) -> float:
    # Random module has betavariate in stdlib.
    return random.betavariate(max(alpha, 0.001), max(beta, 0.001))


def _extract_trade_outcomes() -> list[dict[str, Any]]:
    decisions = _read_jsonl(DATA_DIR / "decisions_log.jsonl")
    out: list[dict[str, Any]] = []
    for row in decisions:
        decision = row.get("decision") if isinstance(row.get("decision"), dict) else row
        outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
        if str(decision.get("action") or "").upper() != "BUY":
            continue
        pnl_pct = outcome.get("pnl_pct")
        if pnl_pct is None:
            continue
        out.append(
            {
                "ticker": decision.get("ticker"),
                "signal_mode": decision.get("signal_mode") or "deterministic_only",
                "strategy": decision.get("strategy_id") or decision.get("source") or "screener",
                "pnl_pct": _safe_float(pnl_pct),
                "metrics": decision.get("metrics") or {},
            }
        )
    return out


def _phase1_self_diagnosis() -> dict[str, Any]:
    risk = get_risk_status()
    brief = _latest_json("fortress_intelligence_brief_*.json")
    analyst = _latest_json("analyst_consensus_*.json")
    issues: list[dict[str, Any]] = []

    try:
        from utils.integrity_diagnostics import issues_for_phase1, run_integrity_scan
        from utils.si_recommendation_queue import process_integrity_scan

        integrity = run_integrity_scan(log=True)
        issues.extend(issues_for_phase1(integrity))
        process_integrity_scan(integrity)
    except Exception as e:
        logger.warning("Integrity scan failed: %s", e)

    buy_recs = [
        r
        for r in (analyst.get("recommendations") or [])
        if isinstance(r, dict) and str(r.get("recommendation") or "").upper() == "BUY"
    ]
    if buy_recs and int((brief.get("execution_analysis") or {}).get("trades_today", {}).get("agentic") or 0) == 0:
        issues.append(
            {
                "severity": "high",
                "title": "Agentic BUY recommendations not converting",
                "fix": "Lower entry-gate friction during approved windows or increase candidate pass-through for agentic symbols.",
            }
        )
    if bool(risk.get("circuit_breaker_active")):
        issues.append(
            {
                "severity": "high",
                "title": "Circuit breaker active",
                "fix": "Verify recent losses and reset only after review; keep paper mode until streak normalizes.",
            }
        )

    blockers = (brief.get("qa_checklist") or {}).get("critical_blockers") or []
    for b in blockers[:5]:
        issues.append({"severity": "medium", "title": str(b), "fix": "Track in optimization queue and re-check after next session."})

    llm_note = ""
    prompt = (
        "Summarize the most important one-line operational fix for a paper trading bot in JSON: "
        '{"top_fix":"..."}'
    )
    llm_resp = call_llm(prompt, timeout=20)
    if "Error:" not in llm_resp:
        llm_note = llm_resp[:400]

    return {"issues": issues, "llm_observation": llm_note}


def _phase2_parameter_tuning() -> dict[str, Any]:
    current = _read_json(DATA_DIR / "current_params.json", {})
    if not isinstance(current, dict) or not current:
        current = {"rsi_threshold": 40, "drop_min": -15, "drop_max": -5, "volume_ratio_min": 1.5}

    outcomes = _extract_trade_outcomes()
    wins = [o for o in outcomes if float(o.get("pnl_pct", 0.0)) > 0]
    losses = [o for o in outcomes if float(o.get("pnl_pct", 0.0)) <= 0]
    win_rate = (len(wins) / len(outcomes)) if outcomes else 0.0

    proposed = dict(current)
    rationale = []
    # Lightweight Bayesian-style nudge.
    if outcomes and win_rate < 0.5:
        proposed["rsi_threshold"] = max(32, int(current.get("rsi_threshold", 40)) - 1)
        proposed["volume_ratio_min"] = round(max(1.1, _safe_float(current.get("volume_ratio_min", 1.5)) + 0.05), 2)
        rationale.append("Win rate below 50%; tighten entries (lower RSI threshold, higher volume filter).")
    elif outcomes and win_rate > 0.65:
        proposed["rsi_threshold"] = min(55, int(current.get("rsi_threshold", 40)) + 1)
        proposed["drop_max"] = min(0, int(current.get("drop_max", -5)) + 1)
        rationale.append("Win rate above 65%; cautiously increase throughput.")
    elif not outcomes:
        try:
            from utils.classic_si_screener import maybe_auto_relax_screener, screening_context

            screener_si = maybe_auto_relax_screener()
            ctx = screening_context()
            rationale.append(
                f"No closed trades in window — screener SI context: "
                f"zero_streak={ctx.get('consecutive_zero_runs')} regime={ctx.get('regime')}."
            )
            return {
                "observed_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "current_params": current,
                "proposed_params": current,
                "rationale": rationale,
                "screener_si": screener_si,
            }
        except Exception as e:
            rationale.append(f"No trades; screener SI skipped: {e}")
    else:
        rationale.append("Insufficient edge shift; hold parameters steady.")

    return {
        "observed_trades": len(outcomes),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "current_params": current,
        "proposed_params": proposed,
        "rationale": rationale,
    }


def _phase3_strategy_ab() -> dict[str, Any]:
    outcomes = _extract_trade_outcomes()
    buckets: dict[str, dict[str, int]] = {}
    for o in outcomes:
        key = str(o.get("signal_mode") or "deterministic_only")
        rec = buckets.setdefault(key, {"wins": 0, "losses": 0})
        if float(o.get("pnl_pct") or 0.0) > 0:
            rec["wins"] += 1
        else:
            rec["losses"] += 1
    if "deterministic_only" not in buckets:
        buckets["deterministic_only"] = {"wins": 1, "losses": 1}
    if "agentic_signal_boost" not in buckets:
        buckets["agentic_signal_boost"] = {"wins": 1, "losses": 1}

    sampled: dict[str, float] = {}
    for k, v in buckets.items():
        sampled[k] = _beta_sample(v["wins"] + 1, v["losses"] + 1)
    total = sum(sampled.values()) or 1.0
    allocation = {k: round((v / total) * 100, 2) for k, v in sampled.items()}
    return {"bandit_samples": sampled, "allocation_pct": allocation, "observations": buckets}


def _phase4_autonomous_changes(phase2: dict[str, Any]) -> dict[str, Any]:
    """
    Produce autonomous change proposal and optionally apply safe parameter changes.
    """
    allow_writes = str(os.getenv("FORTRESS_EVOLUTION_ALLOW_WRITES", "0")).strip().lower() in {"1", "true", "yes", "on"}
    require_approval = str(os.getenv("FORTRESS_EVOLUTION_REQUIRE_APPROVAL", "1")).strip().lower() in {
        "1", "true", "yes", "on"
    }
    max_param_delta = float(os.getenv("FORTRESS_EVOLUTION_MAX_PARAM_DELTA_PCT", "0.20"))
    proposed = phase2.get("proposed_params") or {}
    current = phase2.get("current_params") or {}
    changed = {k: v for k, v in proposed.items() if current.get(k) != v}

    # Safeguard: bound one-step parameter jump sizes.
    bounded_changes: dict[str, Any] = {}
    blocked_changes: dict[str, str] = {}
    for k, v in changed.items():
        cur = current.get(k)
        try:
            curf = float(cur)
            vf = float(v)
            if abs(curf) < 1e-9:
                bounded_changes[k] = v
                continue
            rel = abs((vf - curf) / abs(curf))
            if rel > max_param_delta:
                blocked_changes[k] = f"delta_pct={rel:.3f}>{max_param_delta:.3f}"
                continue
            bounded_changes[k] = v
        except Exception:
            # Non-numeric params are allowed but never auto-applied without approval.
            bounded_changes[k] = v

    proposal = {
        "change_type": "parameter_patch",
        "target_file": "data/current_params.json",
        "changes": bounded_changes,
        "blocked_changes": blocked_changes,
        "requires_approval": require_approval,
        "apply_mode": "auto" if allow_writes else "dry_run",
    }

    applied = False
    if allow_writes and bounded_changes and not require_approval:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            payload = dict(current)
            payload.update(bounded_changes)
            payload["updated_by"] = "recursive_evolution"
            payload["updated_at"] = datetime.now().isoformat()
            (DATA_DIR / "current_params.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            applied = True
        except Exception as e:
            proposal["apply_error"] = str(e)
    elif bounded_changes and require_approval:
        try:
            queue_path = DATA_DIR / "evolution_change_approval_queue.jsonl"
            row = {
                "timestamp": datetime.now().isoformat(),
                "proposal": proposal,
                "status": "pending_approval",
            }
            with open(queue_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception:
            pass

    return {"proposal": proposal, "applied": applied}


def _phase5_meta_learning(phase1: dict[str, Any], phase2: dict[str, Any], phase3: dict[str, Any], phase4: dict[str, Any]) -> dict[str, Any]:
    state_path = DATA_DIR / "meta_learning_state.json"
    state = _read_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    history = state.get("history") if isinstance(state.get("history"), list) else []
    record = {
        "timestamp": datetime.now().isoformat(),
        "issues_count": len(phase1.get("issues") or []),
        "win_rate": phase2.get("win_rate"),
        "suggested_allocation": phase3.get("allocation_pct"),
        "changes_applied": bool(phase4.get("applied")),
    }
    history.append(record)
    history = history[-200:]

    # Simple trend score: average recent win_rate delta.
    recent = [r for r in history if isinstance(r.get("win_rate"), (int, float))]
    trend = 0.0
    if len(recent) >= 2:
        diffs = [float(recent[i]["win_rate"]) - float(recent[i - 1]["win_rate"]) for i in range(1, len(recent))]
        trend = sum(diffs[-20:]) / max(1, len(diffs[-20:]))
    out = {"history": history, "learning_trend": round(trend, 6), "loops_completed": len(history)}
    state_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def run_recursive_evolution(*, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    del data_dir  # kept for future override compatibility.
    logger.info("Starting recursive evolution cycle")
    p1 = _phase1_self_diagnosis()
    p2 = _phase2_parameter_tuning()
    p3 = _phase3_strategy_ab()
    p4 = _phase4_autonomous_changes(p2)
    p5 = _phase5_meta_learning(p1, p2, p3, p4)
    llm_meta: dict[str, Any] = {"patterns": [], "insights": [], "recommendations": [], "new_strategy": None}
    trades = _extract_trade_outcomes()
    if len(trades) >= 10:
        engine = LLMReasoningEngine()
        llm_meta = engine.discover_patterns(trades)
        perf = {
            "total_trades": len(trades),
            "win_rate": round(sum(1 for t in trades if float(t.get("pnl_pct") or 0.0) > 0) / max(1, len(trades)), 4),
            "avg_pnl_pct": round(sum(float(t.get("pnl_pct") or 0.0) for t in trades) / max(1, len(trades)), 4),
        }
        llm_meta["new_strategy"] = engine.generate_new_strategy(perf)

    llm_learning_review: dict[str, Any] = {}
    try:
        llm_learning_review = LLMLearningAgent().daily_learning_review()
    except Exception as e:
        logger.warning("LLM learning review failed: %s", e)
        llm_learning_review = {"error": str(e)}

    result = {
        "timestamp": datetime.now().isoformat(),
        "phase1_self_diagnosis": p1,
        "phase2_parameter_tuning": p2,
        "phase3_strategy_ab_testing": p3,
        "phase4_autonomous_changes": p4,
        "phase5_meta_learning": p5,
        "llm_pattern_discovery": llm_meta,
        "llm_learning_review": llm_learning_review,
        "safety": {
            "paper_only_recommended": True,
            "autonomous_writes_enabled": str(os.getenv("FORTRESS_EVOLUTION_ALLOW_WRITES", "0")).strip().lower()
            in {"1", "true", "yes", "on"},
            "notes": "Code deployment is never auto-executed by evolve; only parameter patching can auto-apply when explicitly enabled.",
        },
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DATA_DIR / f"recursive_evolution_{ts}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("Recursive evolution cycle complete: %s", out_path)

    try:
        from utils.cron_heartbeat import record_success

        record_success("recursive_evolution")
    except Exception:
        pass

    policy_recovery: dict[str, Any] = {}
    try:
        from utils.policy_guardrails import maybe_clear_forced_rollback_on_recovery

        drift = _read_json(DATA_DIR / "drift_report.json", {})
        if isinstance(drift, dict) and drift:
            cleared = maybe_clear_forced_rollback_on_recovery(drift)
            if cleared:
                policy_recovery = cleared
                result["policy_recovery"] = policy_recovery
                out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Policy recovery hook failed: %s", e)

    try:
        from utils.fused_signal_model import propose_weight_tuning_from_ledger
        from utils.si_recommendation_queue import upsert_from_finding

        finding = propose_weight_tuning_from_ledger()
        if finding:
            result["fused_signal_weight_proposal"] = upsert_from_finding(finding, source="integrity_scan")
            out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Fused signal reweight hook failed: %s", e)

    return result

