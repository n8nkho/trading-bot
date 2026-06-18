"""
Classic autonomous SI — assess queue, auto-apply screener patches, optional code agent.

Runs without human go when FORTRESS_CLASSIC_SI_AUTO=1.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from utils.system_time import now_iso

_ROOT = Path(__file__).resolve().parent.parent
_FORTRESS_AI = Path("/home/ubuntu/fortress-ai")

_SCREENER_CODES = frozenset(
    {
        "classic_zero_candidates",
        "classic_candidate_throughput",
        "classic_fill_recency",
        "classic_screener_throughput",
    }
)
_ENTRY_CODES = frozenset({"classic_fill_recency", "classic_fill_recency_gap"})


def auto_enabled() -> bool:
    return str(os.environ.get("FORTRESS_CLASSIC_SI_AUTO", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _heuristic_assess(item: dict[str, Any]) -> dict[str, Any]:
    code = str(item.get("code") or "")
    worth = code in _SCREENER_CODES or code in _ENTRY_CODES or code.startswith("classic_")
    plan = str(item.get("recommendation") or "")
    if code in _SCREENER_CODES:
        plan += (
            "\nAuto-apply: utils/classic_si_screener.maybe_auto_relax_screener() "
            "and verify agents/screener_agent.py reads screener_si_overrides.json."
        )
    if code in _ENTRY_CODES:
        plan += (
            "\nAuto-apply: utils/classic_si_entry.maybe_auto_relax_entry_gate() "
            "and verify agents/entry_agent.py reads entry_si_overrides.json."
        )
    return {
        "worth_implementing": worth,
        "rationale": f"Classic SI heuristic code={code}",
        "proposed_implementation": plan[:8000],
        "reviewer": "classic_si_heuristic",
    }


def auto_assess_item(item_id: str) -> dict[str, Any]:
    from utils.si_recommendation_queue import (
        DISPOSITION_AUTO_APPLY_QUEUED,
        DISPOSITION_PENDING_HUMAN,
        is_cross_stack_item,
        load_queue,
        save_queue,
    )

    queue = load_queue()
    item = next((x for x in queue.get("items") or [] if x.get("id") == item_id), None)
    if not item:
        raise KeyError(f"item_not_found:{item_id}")

    assessed = _heuristic_assess(item)
    item["agent_assessment"] = {**assessed, "assessed_utc": now_iso()}
    if is_cross_stack_item(item):
        item["disposition"] = DISPOSITION_PENDING_HUMAN
        item["requires_human_go"] = True
    elif assessed.get("worth_implementing"):
        item["disposition"] = DISPOSITION_AUTO_APPLY_QUEUED if auto_enabled() else DISPOSITION_PENDING_HUMAN
    else:
        item["status"] = "closed"
        item["disposition"] = "dismissed"
        item["closed_reason"] = "auto_assess_dismissed"
    item["updated_utc"] = now_iso()

    for i, row in enumerate(queue.get("items") or []):
        if row.get("id") == item_id:
            queue["items"][i] = item
            break
    save_queue(queue)
    return item


def auto_assess_pending(*, limit: int = 5) -> list[dict[str, Any]]:
    from utils.si_recommendation_queue import DISPOSITION_PENDING_AGENT, list_pending

    out: list[dict[str, Any]] = []
    for item in list_pending(limit=limit):
        if item.get("disposition") != DISPOSITION_PENDING_AGENT:
            continue
        try:
            out.append(auto_assess_item(str(item["id"])))
        except Exception as e:
            out.append({"id": item.get("id"), "error": str(e)[:120]})
    return out


def apply_screener_item(item: dict[str, Any]) -> dict[str, Any]:
    from utils.classic_si_screener import maybe_auto_relax_screener

    result = maybe_auto_relax_screener()
    if result.get("ok"):
        return {"ok": True, "mode": "screener_relax", **result}
    return {"ok": False, "skipped": result.get("skipped"), "detail": result}


def apply_entry_item(item: dict[str, Any]) -> dict[str, Any]:
    from utils.classic_si_entry import maybe_auto_relax_entry_gate

    result = maybe_auto_relax_entry_gate()
    if result.get("ok"):
        return {"ok": True, "mode": "entry_relax", **result}
    return {"ok": False, "skipped": result.get("skipped"), "detail": result}


def apply_queued_item(item_id: str) -> dict[str, Any]:
    from utils.si_recommendation_queue import is_cross_stack_item, load_queue, mark_implemented

    queue = load_queue()
    item = next((x for x in queue.get("items") or [] if x.get("id") == item_id), None)
    if not item:
        raise KeyError(f"item_not_found:{item_id}")

    if is_cross_stack_item(item):
        hg = item.get("human_go") if isinstance(item.get("human_go"), dict) else {}
        if not hg.get("approved"):
            return {
                "ok": False,
                "skipped": "cross_stack_requires_human_go",
                "item_id": item_id,
            }

    code = str(item.get("code") or "")
    if code in _SCREENER_CODES:
        result = apply_screener_item(item)
    elif code in _ENTRY_CODES:
        result = apply_entry_item(item)
    else:
        result = _try_fortress_code_agent(item)

    if result.get("ok"):
        mark_implemented(item_id, note=f"classic_si_auto:{code}:{result.get('mode')}")
    return {"item_id": item_id, "code": code, **result}


def _try_fortress_code_agent(item: dict[str, Any]) -> dict[str, Any]:
    """Delegate non-screener code fixes to fortress-ai si_code_implementation."""
    if not _FORTRESS_AI.is_dir():
        return {"ok": False, "skipped": "fortress_ai_missing"}
    try:
        import sys

        if str(_FORTRESS_AI) not in sys.path:
            sys.path.insert(0, str(_FORTRESS_AI))
        from utils.si_code_implementation import implement_item

        return implement_item(str(item["id"]), dry_run=False)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def apply_queued(*, limit: int = 2) -> list[dict[str, Any]]:
    from utils.si_recommendation_queue import DISPOSITION_AUTO_APPLY_QUEUED, load_queue

    out: list[dict[str, Any]] = []
    for item in load_queue().get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "open":
            continue
        if item.get("disposition") != DISPOSITION_AUTO_APPLY_QUEUED:
            continue
        try:
            out.append(apply_queued_item(str(item["id"])))
        except Exception as e:
            out.append({"ok": False, "error": str(e)[:120]})
        if len(out) >= limit:
            break
    return out


def ingest_fortress_capability_gaps() -> list[dict[str, Any]]:
    """Pull Classic objective gaps from fortress-ai capability report → local queue."""
    from utils.si_recommendation_queue import upsert_from_finding

    report_path = _FORTRESS_AI / "data" / "si_capability" / "latest.json"
    if not report_path.is_file():
        return []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    upserted: list[dict[str, Any]] = []
    gaps = report.get("objective_gaps") or []
    classic = (report.get("metrics") or {}).get("classic_fortress") or {}

    for gap in gaps:
        if str(gap.get("component") or "") != "classic_fortress":
            continue
        oid = str(gap.get("objective_id") or "")
        code = "classic_screener_throughput"
        if oid == "classic_fill_recency":
            code = "classic_fill_recency"
        elif oid == "classic_candidate_throughput":
            code = "classic_candidate_throughput"
        elif oid == "classic_fill_activity":
            code = "classic_fill_recency"

        finding = {
            "code": code,
            "objective_id": oid,
            "severity": "high" if gap.get("priority") == "critical" else "medium",
            "component": "classic_fortress",
            "title": f"Classic objective gap: {oid}",
            "recommendation": (
                f"{oid}: {gap.get('metric')}={gap.get('value')} "
                f"(target gap={gap.get('gap')}); regime={classic.get('latest_regime')}; "
                f"days_since_fill={classic.get('days_since_last_fill')}."
            ),
            "effort": "low",
            "impact": gap.get("priority") or "high",
            "kind": "tunable",
        }
        upserted.append(upsert_from_finding(finding, source="capability_review"))

    for rec in report.get("classic_recommendations") or []:
        if not isinstance(rec, dict):
            continue
        action = str(rec.get("action") or "")
        code = "classic_screener_throughput"
        if "fill" in action:
            code = "classic_fill_recency"
        finding = {
            "code": code,
            "severity": "medium",
            "component": "classic_fortress",
            "title": f"Classic SI: {action}",
            "recommendation": str(rec.get("detail") or ""),
            "effort": "low",
            "impact": "high",
            "kind": "tunable",
        }
        upserted.append(upsert_from_finding(finding, source="capability_review"))

    return upserted


def scan_zero_candidate_finding() -> dict[str, Any] | None:
    from utils.classic_si_screener import screening_context, should_auto_relax

    ctx = screening_context()
    ok, reason = should_auto_relax(min_zero_runs=2)
    if not ok and ctx["consecutive_zero_runs"] < 2:
        return None
    if ctx["last_candidates_found"] > 0 and ctx["consecutive_zero_runs"] < 2:
        return None
    return {
        "code": "classic_zero_candidates",
        "severity": "high" if ctx["consecutive_zero_runs"] >= 3 else "medium",
        "component": "classic_fortress",
        "title": "Consecutive zero-candidate screens",
        "recommendation": (
            f"{ctx['consecutive_zero_runs']} zero screens in {ctx['regime']} — "
            "relax bear/ranging screener tier-1 via classic_si_screener."
        ),
        "consecutive_zero_runs": ctx["consecutive_zero_runs"],
        "regime": ctx["regime"],
        "filter_counts": ctx.get("filter_counts"),
        "kind": "tunable",
        "effort": "low",
        "impact": "high",
        "si_action": reason,
    }


def run_classic_si_cycle(*, assess_limit: int = 5, apply_limit: int = 2) -> dict[str, Any]:
    from utils.classic_si_screener import maybe_auto_relax_screener, screening_context
    from utils.si_recommendation_queue import upsert_from_finding

    if not auto_enabled():
        return {"ok": True, "skipped": "classic_si_auto_disabled"}

    ingested = ingest_fortress_capability_gaps()
    zf = scan_zero_candidate_finding()
    if zf:
        upsert_from_finding(zf, source="classic_si_scan")

    assessed = auto_assess_pending(limit=assess_limit)
    applied = apply_queued(limit=apply_limit)

    # Direct screener relax when streak persists even if queue empty
    direct = {}
    ctx = screening_context()
    if ctx["consecutive_zero_runs"] >= 2 and not any(a.get("ok") for a in applied):
        direct = maybe_auto_relax_screener()

    entry_direct = {}
    try:
        from utils.fill_recency_entry import days_since_last_activity
        from utils.classic_si_entry import maybe_auto_relax_entry_gate

        if (days_since_last_activity() or 0) >= 7:
            entry_direct = maybe_auto_relax_entry_gate()
    except Exception:
        entry_direct = {}

    return {
        "ok": True,
        "ts": now_iso(),
        "ingested": len(ingested),
        "assessed": len(assessed),
        "applied": applied,
        "direct_screener": direct,
        "direct_entry": entry_direct,
        "context": ctx,
    }
