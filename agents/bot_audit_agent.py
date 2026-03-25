"""
Bot Audit Agent

Purpose:
  Provide an operator-facing daily audit of the system against objectives:
    - keep losses near zero (risk discipline / realized PnL health)
    - maintain profit opportunities (signal-to-trade throughput + win rate)

Key design goals:
  - Read-only: no trading / no broker submission / no network.
  - Deterministic: derives metrics only from local JSON/JSONL + log tails.
  - Safe for Command Center "run anytime": fast, avoids heavy parsing.
  - Explainable: returns `findings` + `recommendations` with reasons.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pytz


ET = pytz.timezone("America/New_York")


DEFAULT_DATA_DIR = Path("data")
DEFAULT_LOGS_DIR = Path("logs")


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def _parse_timestamp_local_iso(ts: Any) -> datetime | None:
    """
    Parse ISO timestamps from ledger/registry.

    If timestamps have no timezone, interpret them in server-local time.
    For objective comparisons we then derive an ET date string.
    """
    if not ts:
        return None
    try:
        s = str(ts).strip()
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # Interpret as local server time.
            dt = dt.replace(tzinfo=timezone.utc).astimezone(ET)
        else:
            dt = dt.astimezone(ET)
        return dt
    except Exception:
        return None


def _read_text_tail(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
        return txt[-max_chars:]
    except OSError:
        return ""


def _extract_strategy_key(rec: dict[str, Any]) -> str:
    """
    Attempt to label a ledger row by its originating strategy/source.
    """
    for k in ("strategy_id", "strategy", "source", "type"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Fallbacks for older/variant rows.
    ticker = rec.get("ticker") or rec.get("symbol") or "UnknownTicker"
    return f"UnknownStrategy({ticker})"


def _audit_objective_loss_health(
    *,
    pnl_today: float,
    wins_today: int,
    losses_today: int,
    total_today: int,
    consecutive_losses: int | None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Returns (status, findings[]).
    """
    findings: list[dict[str, Any]] = []

    loss_rate = (losses_today / total_today * 100.0) if total_today else None
    if loss_rate is not None:
        findings.append(
            {
                "metric": "loss_rate_today_pct",
                "value": round(loss_rate, 2),
                "target": "<= 40% (heuristic)",
            }
        )

    findings.append({"metric": "realized_pnl_today", "value": round(pnl_today, 2), "target": ">= -X (heuristic)"})

    if consecutive_losses is not None:
        findings.append(
            {
                "metric": "risk_guardian_consecutive_losses",
                "value": int(consecutive_losses),
                "target": "<= 1 for near-zero-loss objective",
            }
        )

    # Heuristic status:
    # - "ok" if pnl_today >= 0 and losses <= wins (or no trades)
    # - "warn" if pnl_today < 0 but not catastrophic
    # - "critical" if pnl_today is negative AND loss rate high OR circuit breaker-like streak.
    status = "warn"
    if total_today == 0:
        status = "ok"
        findings.append({"metric": "trade_count_today", "value": 0, "target": "ok"})
    else:
        if pnl_today >= 0 and (losses_today <= wins_today):
            status = "ok"
        else:
            high_loss_rate = (loss_rate is not None) and (loss_rate >= 60)
            bad_streak = (consecutive_losses is not None) and (int(consecutive_losses) >= 3)
            if high_loss_rate or bad_streak:
                status = "critical"

    return status, findings


def _audit_objective_profit_opportunities(
    *,
    total_today: int,
    wins_today: int,
    total_lb: int,
    wins_lb: int,
) -> tuple[str, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    win_rate_today = (wins_today / total_today * 100.0) if total_today else None
    win_rate_lb = (wins_lb / total_lb * 100.0) if total_lb else None

    findings.append({"metric": "executed_trades_today", "value": total_today, "target": ">= 1"})
    if win_rate_today is not None:
        findings.append({"metric": "win_rate_today_pct", "value": round(win_rate_today, 2), "target": ">= 45%"})
    if win_rate_lb is not None:
        findings.append(
            {
                "metric": "win_rate_lookback_pct",
                "value": round(win_rate_lb, 2),
                "target": ">= 45% (heuristic)",
            }
        )

    status = "warn"
    if total_today == 0 and total_lb == 0:
        status = "warn"
        findings.append({"metric": "throughput", "value": "no ledger fills", "target": "needs data"})
    else:
        if win_rate_today is not None and win_rate_today >= 50 and total_today >= 1:
            status = "ok"
        elif total_today >= 1:
            status = "warn"
        else:
            status = "critical"
            findings.append({"metric": "throughput", "value": "0 fills today", "target": ">= 1"})

    return status, findings


def audit_bot_performance(
    *,
    data_dir: Path | None = None,
    logs_dir: Path | None = None,
    lookback_days: int = 30,
    audit_days: int = 1,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """
    Read-only audit. Returns a JSON-serializable report.
    """
    data_dir = data_dir or DEFAULT_DATA_DIR
    logs_dir = logs_dir or DEFAULT_LOGS_DIR
    now_utc = now_utc or datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)

    # Use "ET date" for objective evaluation to match operator expectations.
    day0 = now_et.date()
    day_start_lb = (now_utc - timedelta(days=lookback_days)).date()

    ledger_path = data_dir / "pnl_ledger.jsonl"
    risk_state_path = data_dir / "risk_guardian_state.json"
    operational_runs_path = data_dir / "operational_runs.jsonl"
    last_screening_meta_path = data_dir / "last_screening_meta.json"

    # Risk guardian consecutive losses (if persisted).
    consecutive_losses: int | None = None
    if risk_state_path.exists():
        try:
            st = json.loads(risk_state_path.read_text(encoding="utf-8"))
            consecutive_losses = int(st.get("consecutive_losses")) if st.get("consecutive_losses") is not None else None
        except Exception:
            consecutive_losses = None

    # Ledger stats.
    pnl_today = 0.0
    wins_today = 0
    losses_today = 0
    total_today = 0

    pnl_lb = 0.0
    wins_lb = 0
    losses_lb = 0
    total_lb = 0

    by_strategy: dict[str, dict[str, Any]] = {}
    recent_rows: list[dict[str, Any]] = []

    for rec in _iter_jsonl(ledger_path):
        if not isinstance(rec, dict):
            continue
        pnl = _safe_float(rec.get("pnl"))
        if pnl is None:
            continue
        ts = _parse_timestamp_local_iso(rec.get("timestamp"))
        if ts is None:
            continue
        rec_day = ts.date()

        if rec_day == day0:
            total_today += 1
            pnl_today += pnl
            if pnl > 0:
                wins_today += 1
            elif pnl < 0:
                losses_today += 1

        if rec_day >= day_start_lb:
            total_lb += 1
            pnl_lb += pnl
            if pnl > 0:
                wins_lb += 1
            elif pnl < 0:
                losses_lb += 1

        # Strategy breakdown.
        sk = _extract_strategy_key(rec)
        st = by_strategy.setdefault(sk, {"strategy": sk, "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        st["trades"] += 1
        st["pnl"] += pnl
        if pnl > 0:
            st["wins"] += 1
        elif pnl < 0:
            st["losses"] += 1

        recent_rows.append(rec)
        if len(recent_rows) > 50:
            recent_rows.pop(0)

    # Process stats (registry run success).
    process = {"today_screening_runs": [], "recent_screening_runs": [], "notes": []}
    if operational_runs_path.exists():
        try:
            # Only read a limited tail for speed.
            ops_rows = list(_iter_jsonl(operational_runs_path))
            # Reduce scan: keep last 400 ops.
            ops_rows = ops_rows[-400:]
            # Group by run_id in a lightweight way.
            by_run: dict[str, dict[str, Any]] = {}
            for ev in ops_rows:
                if not isinstance(ev, dict):
                    continue
                et = ev.get("event_type")
                if et not in (
                    "screening_run_started",
                    "screening_run_completed",
                    "screening_run_failed",
                ):
                    continue
                payload = ev.get("payload") or {}
                rid = payload.get("run_id")
                if not rid:
                    continue
                row = by_run.setdefault(rid, {"run_id": rid, "event_type": et, "payload": {}})
                # terminal rows overwrite payload keys.
                if ev.get("event_type") in ("screening_run_completed", "screening_run_failed"):
                    row["terminal"] = ev.get("event_type")
                    row["payload"] = payload
                    row["timestamp"] = ev.get("timestamp")
                else:
                    row["payload"] = payload
            # Build list and filter by ET day.
            all_runs = []
            for rid, row in by_run.items():
                ts = _parse_timestamp_local_iso(row.get("timestamp")) if row.get("timestamp") else None
                if ts:
                    all_runs.append({**row, "et_date": ts.date().isoformat()})
                else:
                    all_runs.append({**row, "et_date": None})
            all_runs_sorted = sorted(all_runs, key=lambda x: x.get("timestamp") or "", reverse=True)
            process["recent_screening_runs"] = all_runs_sorted[:8]
            process["today_screening_runs"] = [r for r in all_runs_sorted if r.get("et_date") == day0.isoformat()][:6]
        except Exception as e:
            process["notes"].append(f"operational_runs parse error: {type(e).__name__}:{e}")

    last_meta = {}
    if last_screening_meta_path.exists():
        try:
            last_meta = json.loads(last_screening_meta_path.read_text(encoding="utf-8"))
        except Exception:
            last_meta = {}

    # Objective evaluation
    loss_status, loss_findings = _audit_objective_loss_health(
        pnl_today=pnl_today,
        wins_today=wins_today,
        losses_today=losses_today,
        total_today=total_today,
        consecutive_losses=consecutive_losses,
    )
    profit_status, profit_findings = _audit_objective_profit_opportunities(
        total_today=total_today,
        wins_today=wins_today,
        total_lb=total_lb,
        wins_lb=wins_lb,
    )

    overall_status = "warn"
    if loss_status == "critical" or profit_status == "critical":
        overall_status = "critical"
    elif loss_status == "ok" and profit_status == "ok":
        overall_status = "ok"

    # Recommendations: deterministic heuristics.
    recommendations: list[dict[str, Any]] = []
    if overall_status in ("critical", "warn"):
        if total_today == 0:
            recommendations.append(
                {
                    "severity": "high" if overall_status == "critical" else "medium",
                    "title": "No fills today — check opportunity→execution path",
                    "body": "Ledger shows 0 realized P&L rows for today. Verify cron scheduling (screen/snipe/spy_swing), execution_mode, and that orders were not deferred or blocked by pre_trade_gate.",
                    "action": "operator: run `python3 orchestrator.py screen` (then execute_pending if HITL) and/or check `crontab -l` + `logs/sniper.log` freshness.",
                }
            )
        if loss_status != "ok":
            recommendations.append(
                {
                    "severity": "high" if loss_status == "critical" else "medium",
                    "title": "Loss discipline degraded — tighten gates",
                    "body": "Objective near-zero-loss looks unhealthy for today. Consider switching profile to capital_preservation, enforcing shadow-only for high-vol agents, and reviewing risk_guardian circuit breaker state.",
                    "action": "operator: set `TRADING_POLICY_PROFILE=capital_preservation` or activate operator halt if needed; review `data/risk_guardian_state.json`.",
                }
            )

    # Always include agent breakdown guidance.
    strategies_sorted = sorted(by_strategy.values(), key=lambda x: x.get("pnl", 0.0))
    worst = strategies_sorted[:4]
    best = list(reversed(strategies_sorted))[:4]

    # Only recommend if we have data.
    if by_strategy:
        recommendations.append(
            {
                "severity": "low",
                "title": "Agent-level performance: focus worst offenders",
                "body": f"Worst: {[w['strategy'] + ' pnl=' + str(round(w['pnl'], 2)) for w in worst]} ; Best: {[b['strategy'] + ' pnl=' + str(round(b['pnl'], 2)) for b in best]}",
                "action": "operator: disable or shadow-only the worst-performing strategy via config/profile, then rerun paper for 1-2 sessions.",
            }
        )

    return {
        "timestamp": now_et.isoformat(),
        "objective_day_et": day0.isoformat(),
        "lookback_days": lookback_days,
        "audited": {
            "ledger_path": str(ledger_path),
            "ledger_rows_considered_lb": total_lb,
            "ledger_rows_today": total_today,
        },
        "objectives": {
            "profit_opportunities": {
                "status": profit_status,
                "findings": profit_findings,
            },
            "near_zero_losses": {
                "status": loss_status,
                "findings": loss_findings,
            },
        },
        "process": {
            "today_screening_runs_count": len(process.get("today_screening_runs") or []),
            "recent_screening_runs": process.get("recent_screening_runs") or [],
            "last_screening_meta_loaded": bool(last_meta),
            "last_screening_meta_strict_mode": last_meta.get("strict_mode") if isinstance(last_meta, dict) else None,
        },
        "agent_performance": {
            "worst_strategies": [
                {"strategy": w["strategy"], "trades": w["trades"], "wins": w["wins"], "losses": w["losses"], "pnl": round(w["pnl"], 2)}
                for w in worst
            ],
            "best_strategies": [
                {"strategy": b["strategy"], "trades": b["trades"], "wins": b["wins"], "losses": b["losses"], "pnl": round(b["pnl"], 2)}
                for b in best
            ],
        },
        "recommendations": recommendations,
        "log_tails": {
            "orchestrator.log_tail": _read_text_tail(logs_dir / "orchestrator.log", 1600),
            "sniper.log_tail": _read_text_tail(logs_dir / "sniper.log", 1200),
            "spy_swing.log_tail": _read_text_tail(logs_dir / "spy_swing.log", 1200),
        },
        "overall_status": overall_status,
    }

