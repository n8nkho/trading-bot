"""
Walk-forward gate for prompt promotion — reuses ledger-based validator criteria.

Default off: FORTRESS_PROMPT_WF_GATE_ENABLED=0.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"

DISPOSITION_PENDING_WF_FAIL = "pending_walk_forward_fail"


def gate_enabled() -> bool:
    return str(os.environ.get("FORTRESS_PROMPT_WF_GATE_ENABLED", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def report_path(candidate_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in candidate_id)[:80]
    return _DATA / f"walk_forward_report_prompt_{safe}.json"


def run_prompt_walk_forward(candidate_id: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    from agents.walk_forward_validator import compute_walk_forward_report

    base = compute_walk_forward_report()
    report = {
        **base,
        "candidate_id": candidate_id,
        "kind": "prompt_evolution",
        "metadata": metadata or {},
    }
    _DATA.mkdir(parents=True, exist_ok=True)
    report_path(candidate_id).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def promotion_allowed(candidate_id: str) -> tuple[bool, str, dict[str, Any] | None]:
    if not gate_enabled():
        return True, "gate_disabled", None
    path = report_path(candidate_id)
    if not path.is_file():
        return False, "missing_walk_forward_report", None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False, "invalid_walk_forward_report", None
    if not isinstance(report, dict):
        return False, "invalid_walk_forward_report", None
    if report.get("stable") is True:
        return True, "walk_forward_pass", report
    return False, f"walk_forward_fail:{report.get('reason')}", report


def ensure_gate_before_promotion(candidate_id: str, *, metadata: dict[str, Any] | None = None) -> None:
    """Run WF if missing; raise RuntimeError when gate enabled and report fails."""
    if not gate_enabled():
        return
    path = report_path(candidate_id)
    if not path.is_file():
        run_prompt_walk_forward(candidate_id, metadata=metadata)
    ok, reason, _ = promotion_allowed(candidate_id)
    if not ok:
        raise RuntimeError(f"prompt_walk_forward_blocked:{reason}")
