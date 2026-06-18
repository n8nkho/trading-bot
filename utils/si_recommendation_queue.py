"""
Classic Fortress SI recommendation queue — same schema as fortress-ai sibling.

Feeds recursive_evolution and surfaces items for Cursor agent + human go-ahead.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from utils.system_time import ensure_system_tz, now_iso, system_tz_name

ensure_system_tz()

_ROOT = Path(__file__).resolve().parent.parent
_FORTRESS_AI = Path("/home/ubuntu/fortress-ai")

DISPOSITION_PENDING_AGENT = "pending_agent_review"
DISPOSITION_PENDING_HUMAN = "pending_human_go"
DISPOSITION_AUTO_APPLY_QUEUED = "auto_apply_queued"
DISPOSITION_AUTO_RESOLVED = "auto_resolved"
DISPOSITION_MONITORING = "monitoring"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_IMPLEMENTED = "implemented"

_AUTO_RECONCILE_SOURCES = frozenset({"integrity_scan", "scan_opportunity", "capability_review"})
CROSS_STACK_SOURCES = frozenset(
    {
        "capability_review",
        "cross_stack_belief",
        "fortress_ai_belief",
    }
)


def is_cross_stack_source(source: str) -> bool:
    return str(source or "") in CROSS_STACK_SOURCES


def _data_dir() -> Path:
    return _ROOT / "data"


def queue_path() -> Path:
    return _data_dir() / "si_recommendation_queue.json"


def load_queue() -> dict[str, Any]:
    p = queue_path()
    if not p.exists():
        return {"version": 1, "items": []}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("items"), list):
            return doc
    except Exception:
        pass
    return {"version": 1, "items": []}


def save_queue(doc: dict[str, Any]) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    queue_path().write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return now_iso()


def _finding_key(code: str, component: str = "", *, objective_id: str = "") -> str:
    base = f"{component}:{code}" if component else str(code)
    if objective_id and code == "si_objective_gap":
        return f"{base}:{objective_id}"
    return base


def finding_key_from_finding(finding: dict[str, Any]) -> str:
    return _finding_key(
        str(finding.get("code") or ""),
        str(finding.get("component") or ""),
        objective_id=str(finding.get("objective_id") or ""),
    )


def _finding_still_active(item: dict[str, Any], findings: list[dict[str, Any]]) -> bool:
    code = str(item.get("code") or "")
    component = str(item.get("component") or "")
    item_oid = str((item.get("finding") or {}).get("objective_id") or "")
    for f in findings:
        if str(f.get("code") or "") != code:
            continue
        if str(f.get("component") or "") != component:
            continue
        f_oid = str(f.get("objective_id") or "")
        if code == "si_objective_gap" and (item_oid or f_oid):
            if item_oid and f_oid:
                return item_oid == f_oid
            return True
        return True
    return False


def reconcile_cleared_findings(
    scan: dict[str, Any],
    *,
    active_findings: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Auto-close open queue items when integrity/opportunity scans no longer report them."""
    findings = active_findings if active_findings is not None else list(scan.get("findings") or [])
    queue = load_queue()
    closed: list[str] = []
    changed = False
    for i, item in enumerate(queue.get("items") or []):
        if not isinstance(item, dict) or item.get("status") != STATUS_OPEN:
            continue
        if item.get("disposition") == DISPOSITION_PENDING_HUMAN:
            continue
        if item.get("disposition") == DISPOSITION_AUTO_APPLY_QUEUED:
            continue
        src = str(item.get("source") or "integrity_scan")
        if src not in _AUTO_RECONCILE_SOURCES:
            continue
        if _finding_still_active(item, findings):
            continue
        code = str(item.get("code") or item.get("finding_key") or "")
        item["status"] = STATUS_IMPLEMENTED
        item["disposition"] = DISPOSITION_AUTO_RESOLVED
        item["closed_reason"] = "finding_cleared"
        item["implemented_utc"] = _now_iso()
        item["implementation_note"] = (
            f"Auto-closed: finding no longer active in scan ({code})."
        )[:2000]
        item["updated_utc"] = _now_iso()
        queue["items"][i] = item
        closed.append(code)
        changed = True
    if changed:
        save_queue(queue)
    return closed


def upsert_from_finding(finding: dict[str, Any], *, source: str = "integrity_scan") -> dict[str, Any]:
    code = str(finding.get("code") or "")
    component = str(finding.get("component") or "classic")
    queue = load_queue()
    key = finding_key_from_finding(finding)
    existing = next(
        (x for x in queue.get("items") or [] if x.get("finding_key") == key and x.get("status") == STATUS_OPEN),
        None,
    )
    now = _now_iso()
    item = existing or {
        "id": str(uuid.uuid4()),
        "finding_key": key,
        "created_utc": now,
        "status": STATUS_OPEN,
        "human_go": None,
        "agent_assessment": None,
    }
    disposition = DISPOSITION_PENDING_AGENT
    if is_cross_stack_source(source):
        disposition = DISPOSITION_PENDING_AGENT
    item.update(
        {
            "updated_utc": now,
            "code": code,
            "component": component,
            "title": finding.get("title") or code,
            "severity": finding.get("severity"),
            "recommendation": finding.get("recommendation") or finding.get("fix") or "",
            "disposition": disposition,
            "source": source,
            "finding": finding,
            "effort": finding.get("effort") or "medium",
            "impact": finding.get("impact") or finding.get("severity") or "medium",
            "cross_stack": is_cross_stack_source(source),
        }
    )
    if existing:
        idx = next(i for i, x in enumerate(queue["items"]) if x.get("id") == existing.get("id"))
        queue["items"][idx] = item
    else:
        queue.setdefault("items", []).append(item)
    save_queue(queue)
    return item


def process_integrity_scan(scan: dict[str, Any] | None = None) -> dict[str, Any]:
    from utils.integrity_diagnostics import run_integrity_scan

    scan = scan or run_integrity_scan(log=True)
    items = [upsert_from_finding(f) for f in scan.get("findings") or []]
    auto_resolved = reconcile_cleared_findings(scan)

    sibling_pending: list[dict[str, Any]] = []
    sib = _FORTRESS_AI / "data" / "si_recommendation_summary.json"
    if sib.exists():
        try:
            doc = json.loads(sib.read_text(encoding="utf-8"))
            sibling_pending = doc.get("pending_agent") or []
        except Exception:
            pass

    classic_si: dict[str, Any] = {}
    try:
        from utils.classic_si_autonomous import run_classic_si_cycle

        classic_si = run_classic_si_cycle()
    except Exception as e:
        classic_si = {"error": str(e)[:120]}

    ts = _now_iso()
    summary = {
        "timestamp": ts,
        "system_tz": system_tz_name(),
        "timestamp_utc": ts,
        "classic_items": len(items),
        "auto_resolved": auto_resolved,
        "sibling_pending_agent": len(sibling_pending),
        "classic_si": classic_si,
        "pending_agent": [x for x in load_queue().get("items") or [] if x.get("disposition") == DISPOSITION_PENDING_AGENT and x.get("status") == STATUS_OPEN],
        "pending_human": [x for x in load_queue().get("items") or [] if x.get("disposition") == DISPOSITION_PENDING_HUMAN and x.get("status") == STATUS_OPEN],
        "auto_apply_queued": [x for x in load_queue().get("items") or [] if x.get("disposition") == DISPOSITION_AUTO_APPLY_QUEUED and x.get("status") == STATUS_OPEN],
    }
    (_data_dir() / "si_recommendation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def list_pending(*, limit: int = 50) -> list[dict[str, Any]]:
    out = [
        x
        for x in load_queue().get("items") or []
        if isinstance(x, dict) and x.get("status") == STATUS_OPEN
    ]
    out.sort(key=lambda x: str(x.get("updated_utc") or ""), reverse=True)
    return out[:limit]


def status_dict() -> dict[str, Any]:
    return {
        "queue_size": len(load_queue().get("items") or []),
        "pending_agent_review": [x for x in list_pending() if x.get("disposition") == DISPOSITION_PENDING_AGENT],
        "pending_human_go": [x for x in list_pending() if x.get("disposition") == DISPOSITION_PENDING_HUMAN],
    }


DISPOSITION_DISMISSED = "dismissed"


def set_agent_assessment(
    item_id: str,
    *,
    worth_implementing: bool,
    rationale: str,
    proposed_implementation: str = "",
    reviewer: str = "cursor_agent",
) -> dict[str, Any]:
    queue = load_queue()
    for i, item in enumerate(queue.get("items") or []):
        if item.get("id") != item_id:
            continue
        item["agent_assessment"] = {
            "worth_implementing": bool(worth_implementing),
            "rationale": rationale[:4000],
            "proposed_implementation": proposed_implementation[:8000],
            "reviewer": reviewer,
            "assessed_utc": _now_iso(),
        }
        if worth_implementing:
            try:
                from utils.classic_si_autonomous import auto_enabled

                if auto_enabled():
                    item["disposition"] = DISPOSITION_AUTO_APPLY_QUEUED
                else:
                    item["disposition"] = DISPOSITION_PENDING_HUMAN
            except Exception:
                item["disposition"] = DISPOSITION_PENDING_HUMAN
        else:
            item["disposition"] = DISPOSITION_DISMISSED
            item["status"] = STATUS_CLOSED
            item["closed_reason"] = "agent_dismissed"
        item["updated_utc"] = _now_iso()
        queue["items"][i] = item
        save_queue(queue)
        return item
    raise KeyError(f"item_not_found:{item_id}")


def mark_implemented(item_id: str, *, note: str = "") -> dict[str, Any]:
    queue = load_queue()
    for i, item in enumerate(queue.get("items") or []):
        if item.get("id") != item_id:
            continue
        item["status"] = STATUS_IMPLEMENTED
        item["disposition"] = "auto_resolved"
        item["implemented_utc"] = _now_iso()
        item["implementation_note"] = note[:2000]
        item["updated_utc"] = _now_iso()
        queue["items"][i] = item
        save_queue(queue)
        return item
    raise KeyError(f"item_not_found:{item_id}")
