"""
Classic Fortress integrity scan — feeds recursive_evolution phase-1 diagnosis.
"""
from __future__ import annotations

import glob
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.system_time import ensure_system_tz, now, now_iso, system_tz_name

ensure_system_tz()

_ROOT = Path(__file__).resolve().parent.parent
_FORTRESS_AI = Path("/home/ubuntu/fortress-ai")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def scan_drift_rollback_false_positive() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        from utils.policy_guardrails import get_public_rollback_status, meets_rollback_recovery_criteria

        rb = get_public_rollback_status()
        if not rb.get("forced_profile"):
            return findings
        drift = _read_json(_ROOT / "data" / "drift_report.json", {})
        ok, reason = meets_rollback_recovery_criteria(drift if isinstance(drift, dict) else {})
        if ok:
            findings.append(
                {
                    "code": "drift_rollback_recovery_eligible",
                    "severity": "medium",
                    "component": "classic_policy",
                    "recommendation": f"Clear forced rollback — metrics support recovery: {reason}",
                    "si_action": "clear_rollback_on_recovery",
                }
            )
        else:
            wr = None
            try:
                from utils.policy_guardrails import _pnl_ledger_stats

                st = _pnl_ledger_stats()
                wr = st.get("win_rate")
            except Exception:
                pass
            if wr is not None and float(wr) >= 0.80:
                findings.append(
                    {
                        "code": "drift_rollback_high_win_rate",
                        "severity": "medium",
                        "component": "classic_policy",
                        "win_rate": wr,
                        "recommendation": (
                            "Drift rollback active but ledger win rate >=80% — prefer metric recovery "
                            "over extended capital_preservation lock."
                        ),
                        "si_action": "tune_drift_trigger",
                    }
                )
    except Exception:
        pass
    return findings


def scan_evolution_staleness(*, max_age_days: int = 3) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    files = sorted(glob.glob(str(_ROOT / "data" / "recursive_evolution_*.json")), reverse=True)
    if not files:
        findings.append(
            {
                "code": "evolution_never_run",
                "severity": "high",
                "component": "recursive_evolution",
                "recommendation": "Install 17:10 ET weekday cron for recursive_evolution; verify heartbeat.",
                "si_action": "install_evolution_cron",
            }
        )
        return findings
    latest = Path(files[0])
    try:
        mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=now().tzinfo)
        age_days = (now() - mtime).total_seconds() / 86400.0
        if age_days > max_age_days:
            findings.append(
                {
                    "code": "evolution_stale",
                    "severity": "high",
                    "component": "recursive_evolution",
                    "latest_file": latest.name,
                    "age_days": round(age_days, 1),
                    "recommendation": "recursive_evolution cron missing or failing — check crontab and logs/cron_master.log.",
                    "si_action": "install_evolution_cron",
                }
            )
    except OSError:
        pass
    return findings


def scan_cron_heartbeat() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        from utils.cron_heartbeat import evaluate_heartbeat_health, load_manifest

        hb = evaluate_heartbeat_health(load_manifest(), store_path=_ROOT / "data" / "cron_heartbeats.json")
        if str(hb.get("overall") or "").lower() == "fail":
            alerts = hb.get("alerts") or []
            findings.append(
                {
                    "code": "cron_heartbeat_fail",
                    "severity": "medium",
                    "component": "classic_cron",
                    "alert_count": len(alerts),
                    "recommendation": "Reconcile stale RTH cron jobs vs actual crontab; verify scripts/cron_run.sh heartbeats.",
                    "si_action": "fix_cron_heartbeats",
                }
            )
    except Exception:
        pass
    return findings


def scan_fortress_ai_sibling() -> list[dict[str, Any]]:
    """Cross-repo anomalies from fortress-ai integrity scan when sibling exists."""
    findings: list[dict[str, Any]] = []
    snap = _FORTRESS_AI / "data" / "integrity_scan_latest.json"
    if not snap.exists():
        return findings
    try:
        doc = json.loads(snap.read_text(encoding="utf-8"))
    except Exception:
        return findings
    for f in doc.get("findings") or []:
        if f.get("severity") not in ("critical", "high"):
            continue
        code = str(f.get("code") or "")
        if code in ("exit_notional_blocked", "duplicate_entry_accumulation"):
            try:
                import sys

                sys.path.insert(0, str(_FORTRESS_AI))
                from utils.si_fix_deployment import is_deployed

                if is_deployed(code):
                    continue
            except Exception:
                pass
        findings.append(
            {
                **f,
                "component": f"fortress_ai:{f.get('component')}",
                "recommendation": str(f.get("recommendation") or ""),
            }
        )
    return findings


def scan_regime_stale_rth() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        from utils.market_calendar import is_us_equity_rth_open
        from utils.regime_freshness import regime_age_minutes, regime_is_stale_for_rth

        if not is_us_equity_rth_open():
            return findings
        stale, why = regime_is_stale_for_rth()
        if stale:
            findings.append(
                {
                    "code": "regime_stale_rth",
                    "severity": "high",
                    "component": "classic_regime",
                    "age_minutes": regime_age_minutes(),
                    "recommendation": (
                        "Regime snapshot stale during RTH — auto-refresh via pre_trade_gate or "
                        "run agents.regime_detector."
                    ),
                    "si_action": "refresh_regime",
                }
            )
    except Exception:
        pass
    return findings


def run_integrity_scan(*, log: bool = True) -> dict[str, Any]:
    findings = (
        scan_drift_rollback_false_positive()
        + scan_evolution_staleness()
        + scan_cron_heartbeat()
        + scan_regime_stale_rth()
        + scan_fortress_ai_sibling()
    )
    ts = now_iso()
    out = {
        "timestamp": ts,
        "system_tz": system_tz_name(),
        "timestamp_utc": ts,
        "findings": findings,
        "counts": {
            "critical": sum(1 for f in findings if f.get("severity") == "critical"),
            "high": sum(1 for f in findings if f.get("severity") == "high"),
        },
    }
    p = _ROOT / "data" / "integrity_scan_latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
    if log and findings:
        lp = _ROOT / "data" / "integrity_recommendations.jsonl"
        with open(lp, "a", encoding="utf-8") as f:
            for item in findings:
                f.write(json.dumps({**item, "scan_ts": ts}, default=str) + "\n")
    maybe_auto_run_evolution(out)
    return out


def maybe_auto_run_evolution(scan: dict[str, Any]) -> dict[str, Any] | None:
    """Run recursive evolution when stale — no manual operator step."""
    import os

    if str(os.getenv("FORTRESS_SI_AUTO_RUN_EVOLVE", "1")).strip().lower() not in ("1", "true", "yes", "on"):
        return None
    codes = {str(f.get("code") or "") for f in scan.get("findings") or []}
    if "evolution_stale" not in codes and "evolution_never_run" not in codes:
        return None
    files = sorted(glob.glob(str(_ROOT / "data" / "recursive_evolution_*.json")), reverse=True)
    if files:
        try:
            age_min = (now() - datetime.fromtimestamp(
                Path(files[0]).stat().st_mtime, tz=now().tzinfo
            )).total_seconds() / 60.0
            if age_min < 30:
                return {"skipped": "recent_evolution_run", "age_minutes": round(age_min, 1)}
        except OSError:
            pass
    try:
        from agents.recursive_evolution import run_recursive_evolution

        return run_recursive_evolution()
    except Exception as e:
        return {"error": str(e)[:200]}


def issues_for_phase1(scan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    scan = scan or run_integrity_scan(log=False)
    issues: list[dict[str, Any]] = []
    for f in scan.get("findings") or []:
        sev = str(f.get("severity") or "medium")
        if sev == "info":
            continue
        issues.append(
            {
                "severity": sev,
                "title": str(f.get("code") or "integrity_finding"),
                "fix": str(f.get("recommendation") or ""),
                "si_action": f.get("si_action"),
            }
        )
    return issues
