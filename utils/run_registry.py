"""
Append-only operational run registry — canonical screening lifecycle for operators.
Complements trust_ledger (narrative events) with structured run records + release context.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path("data") / "operational_runs.jsonl"


def _release_context() -> dict[str, Any]:
    ctx = {
        "deploy_commit": (os.environ.get("DEPLOY_COMMIT") or "").strip(),
        "deploy_dirty": (os.environ.get("DEPLOY_DIRTY") or "").strip(),
        "git_head": "",
    }
    try:
        ctx["git_head"] = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, timeout=3
        ).strip()
    except Exception:
        ctx["git_head"] = ""
    return ctx


def append_operational_event(event_type: str, payload: dict[str, Any]) -> None:
    try:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "release": _release_context(),
            "payload": payload or {},
        }
        with open(REGISTRY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


def log_screening_started(run_id: str, policy_profile: str | None, portfolio_value: float) -> None:
    append_operational_event(
        "screening_run_started",
        {
            "run_id": run_id,
            "policy_profile": policy_profile,
            "portfolio_value": portfolio_value,
        },
    )


def log_screening_completed(run_id: str, summary: dict[str, Any]) -> None:
    append_operational_event("screening_run_completed", {"run_id": run_id, **summary})


def log_screening_failed(run_id: str, error_type: str, error: str) -> None:
    append_operational_event(
        "screening_run_failed",
        {"run_id": run_id, "error_type": error_type, "error": str(error)[:2000]},
    )


def read_recent_operational_events(limit: int = 500) -> list[dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return rows[-max(1, int(limit)) :]


def summarize_screening_runs(events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """
    Build one row per run_id from screening_* events (chronological merge).
    """
    evs = events if events is not None else read_recent_operational_events(800)
    by_run: dict[str, dict[str, Any]] = {}
    order = []
    for ev in sorted(evs, key=lambda x: x.get("timestamp") or ""):
        et = ev.get("event_type")
        if et not in (
            "screening_run_started",
            "screening_run_completed",
            "screening_run_failed",
        ):
            continue
        pl = ev.get("payload") or {}
        rid = pl.get("run_id")
        if not rid:
            continue
        if rid not in by_run:
            by_run[rid] = {
                "run_id": rid,
                "started_at": None,
                "finished_at": None,
                "terminal": None,
                "summary": {},
                "release": ev.get("release") or {},
            }
            order.append(rid)
        row = by_run[rid]
        if et == "screening_run_started":
            row["started_at"] = ev.get("timestamp")
            row["summary"].setdefault("policy_profile", pl.get("policy_profile"))
            row["summary"].setdefault("portfolio_value", pl.get("portfolio_value"))
            row["release"] = ev.get("release") or row.get("release") or {}
        elif et == "screening_run_completed":
            row["finished_at"] = ev.get("timestamp")
            row["terminal"] = "completed"
            row["release"] = ev.get("release") or row.get("release") or {}
            row["summary"].update(
                {
                    "candidates_found": pl.get("candidates_found"),
                    "approved_count": pl.get("approved_count"),
                    "executed_count": pl.get("executed_count"),
                    "rejected_count": pl.get("rejected_count"),
                    "strict_mode": pl.get("strict_mode"),
                    "duration_seconds": pl.get("duration_seconds"),
                }
            )
        elif et == "screening_run_failed":
            row["finished_at"] = ev.get("timestamp")
            row["terminal"] = "failed"
            row["release"] = ev.get("release") or row.get("release") or {}
            row["summary"]["error_type"] = pl.get("error_type")
            row["summary"]["error"] = pl.get("error")
    # Newest runs last in order — reverse for UI
    out = [by_run[r] for r in order if r in by_run]
    return list(reversed(out))

