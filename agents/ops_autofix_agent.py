"""
Ops AutoFix Agent (Tier-0 safe actions only).

Current safe actions:
1) Reconcile stale screening runs that never received terminal events.
2) Optionally collapse consecutive duplicate lines in selected logs (with backup).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from utils.market_calendar import is_us_equity_rth_open, session_label
from utils.run_registry import (
    log_screening_failed,
    read_recent_operational_events,
    summarize_screening_runs,
)

DATA_DIR = Path("data")
LOGS_DIR = Path("logs")
REPORT_PREFIX = "ops_autofix_report_"
LATEST_REPORT = DATA_DIR / "ops_autofix_report_latest.json"

logger = logging.getLogger("ops_autofix")
if not logger.handlers:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    _fh = logging.FileHandler(LOGS_DIR / "ops_autofix.log")
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(_fh)


def _to_dt(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _effective_stale_hours(default_hours: float) -> float:
    """
    Adaptive stale threshold:
    - RTH open: keep conservative default (2h)
    - Off-hours/weekend/holiday: reconcile faster (default 1h)
    """
    try:
        lbl = str(session_label())
    except Exception:
        lbl = "unknown"
    try:
        off_hours = float(default_hours)
        off_hours = float(max(0.25, off_hours))
    except Exception:
        off_hours = 2.0
    if lbl in {"closed_after_hours", "closed_weekend", "closed_holiday"}:
        try:
            return float(os.getenv("OPS_AUTOFIX_STALE_HOURS_OFFHOURS", "1.0") or "1.0")
        except Exception:
            return 1.0
    return off_hours


def reconcile_stale_screening_runs(*, stale_after_hours: float = 2.0, dry_run: bool = False) -> dict[str, Any]:
    now = datetime.now()
    effective_hours = _effective_stale_hours(float(stale_after_hours))
    cutoff = now - timedelta(hours=effective_hours)
    runs = summarize_screening_runs(read_recent_operational_events(5000))
    candidates: list[dict[str, Any]] = []
    reconciled: list[str] = []

    for row in runs:
        if row.get("terminal") in {"completed", "failed"} or row.get("finished_at"):
            continue
        rid = row.get("run_id")
        started = _to_dt(row.get("started_at"))
        if not rid or started is None:
            continue
        if started <= cutoff:
            candidates.append(
                {
                    "run_id": rid,
                    "started_at": row.get("started_at"),
                }
            )
            if not dry_run:
                log_screening_failed(
                    str(rid),
                    "stale_in_progress_reconciled",
                    f"Auto-reconciled by ops_autofix at {now.isoformat()} after missing terminal event.",
                )
                reconciled.append(str(rid))

    return {
        "stale_after_hours": stale_after_hours,
        "effective_stale_after_hours": effective_hours,
        "dry_run": dry_run,
        "candidates_count": len(candidates),
        "candidates": candidates,
        "reconciled_count": len(reconciled),
        "reconciled_run_ids": reconciled,
    }


def dedupe_consecutive_log_lines(
    path: Path,
    *,
    dry_run: bool = False,
    max_lines: int = 200_000,
) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "changed": False, "removed": 0}

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    original_n = len(lines)
    if original_n == 0:
        return {"path": str(path), "exists": True, "changed": False, "removed": 0}

    # Bound memory/latency for very large logs.
    if len(lines) > max_lines:
        lines = lines[-max_lines:]

    out: list[str] = []
    prev = None
    removed = 0
    for ln in lines:
        if ln == prev:
            removed += 1
            continue
        out.append(ln)
        prev = ln

    changed = removed > 0
    backup_path = None
    if changed and not dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = str(path.with_suffix(path.suffix + f".bak.{ts}"))
        shutil.copy2(path, backup_path)
        path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")

    return {
        "path": str(path),
        "exists": True,
        "original_lines": original_n,
        "analyzed_lines": len(lines),
        "removed": removed,
        "changed": changed,
        "dry_run": dry_run,
        "backup_path": backup_path,
    }


def run_ops_autofix(
    *,
    dry_run: bool = False,
    stale_after_hours: float = 2.0,
    dedupe_logs: bool = True,
    force_log_dedupe: bool = False,
) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
        "actions": {},
        "summary": {},
    }

    rec = reconcile_stale_screening_runs(stale_after_hours=stale_after_hours, dry_run=dry_run)
    report["actions"]["reconcile_stale_runs"] = rec

    market_open = bool(is_us_equity_rth_open())
    market_state = str(session_label())
    run_log_dedupe = dedupe_logs and (force_log_dedupe or (not market_open))
    dedupe_skipped_reason = None
    if dedupe_logs and not run_log_dedupe:
        dedupe_skipped_reason = "market_open_rth"

    if run_log_dedupe:
        targets = [LOGS_DIR / "sniper.log", LOGS_DIR / "screener.log", LOGS_DIR / "monitor.log"]
        dedupe_out = [dedupe_consecutive_log_lines(p, dry_run=dry_run) for p in targets]
    else:
        dedupe_out = []
    report["actions"]["log_dedupe"] = dedupe_out
    report["actions"]["log_dedupe_enabled"] = bool(dedupe_logs)
    report["actions"]["log_dedupe_forced"] = bool(force_log_dedupe)
    report["actions"]["log_dedupe_ran"] = bool(run_log_dedupe)
    report["actions"]["log_dedupe_skipped_reason"] = dedupe_skipped_reason
    report["actions"]["market_open_rth"] = market_open
    report["actions"]["market_state"] = market_state

    changed_logs = [x.get("path") for x in dedupe_out if x.get("changed")]
    report["summary"] = {
        "reconciled_runs": rec.get("reconciled_count", 0),
        "changed_logs": changed_logs,
        "changed_logs_count": len(changed_logs),
    }

    day = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = DATA_DIR / f"{REPORT_PREFIX}{day}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    LATEST_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    report["latest_report_path"] = str(LATEST_REPORT)
    logger.info(
        "ops_autofix complete dry_run=%s reconciled=%s changed_logs=%s",
        dry_run,
        report["summary"]["reconciled_runs"],
        report["summary"]["changed_logs_count"],
    )
    return report

