"""
Classic Fortress SI recommendation queue — same schema as fortress-ai sibling.

Feeds recursive_evolution and surfaces items for Cursor agent + human go-ahead.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_FORTRESS_AI = Path("/home/ubuntu/fortress-ai")

DISPOSITION_PENDING_AGENT = "pending_agent_review"
DISPOSITION_PENDING_HUMAN = "pending_human_go"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_IMPLEMENTED = "implemented"


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
    return datetime.now(timezone.utc).isoformat()


def _finding_key(code: str, component: str = "") -> str:
    return f"{component}:{code}" if component else str(code)


def upsert_from_finding(finding: dict[str, Any], *, source: str = "integrity_scan") -> dict[str, Any]:
    code = str(finding.get("code") or "")
    component = str(finding.get("component") or "classic")
    queue = load_queue()
    key = _finding_key(code, component)
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
    item.update(
        {
            "updated_utc": now,
            "code": code,
            "component": component,
            "title": finding.get("title") or code,
            "severity": finding.get("severity"),
            "recommendation": finding.get("recommendation") or finding.get("fix") or "",
            "disposition": DISPOSITION_PENDING_AGENT,
            "source": source,
            "finding": finding,
            "effort": finding.get("effort") or "medium",
            "impact": finding.get("impact") or finding.get("severity") or "medium",
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

    # Merge high-severity items from fortress-ai sibling queue
    sibling_pending: list[dict[str, Any]] = []
    sib = _FORTRESS_AI / "data" / "si_recommendation_summary.json"
    if sib.exists():
        try:
            doc = json.loads(sib.read_text(encoding="utf-8"))
            sibling_pending = doc.get("pending_agent") or []
        except Exception:
            pass

    summary = {
        "timestamp_utc": _now_iso(),
        "classic_items": len(items),
        "sibling_pending_agent": len(sibling_pending),
        "pending_agent": [x for x in load_queue().get("items") or [] if x.get("disposition") == DISPOSITION_PENDING_AGENT and x.get("status") == STATUS_OPEN],
        "pending_human": [x for x in load_queue().get("items") or [] if x.get("disposition") == DISPOSITION_PENDING_HUMAN and x.get("status") == STATUS_OPEN],
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
