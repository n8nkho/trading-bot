"""
Central tier / license checks for dashboard, CLI, and scripts.

Lane 1: FORTRESS_LICENSE_TIER=master → all checks pass.
Lanes 2–3: starter / pro / enterprise per config.license + config.tiers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from config.license import Plan, get_plan
from config.tiers import (
    backtest_allowed,
    fortress_allowed,
    trust_ledger_export_allowed,
)


def _ts() -> str:
    return datetime.now().isoformat()


def get_plan_for_gate() -> Plan:
    return get_plan()


def check_license_valid(plan: Plan) -> Optional[Dict[str, Any]]:
    if plan.valid:
        return None
    return {
        "error": "license_invalid",
        "tier": plan.tier,
        "message": "License expired or invalid. Contact support or renew.",
        "timestamp": _ts(),
    }


def check_backtest_access(plan: Plan) -> Optional[Dict[str, Any]]:
    v = check_license_valid(plan)
    if v:
        return v
    if backtest_allowed(plan.tier):
        return None
    return {
        "error": "tier_gate",
        "feature": "backtest",
        "tier": plan.tier,
        "message": "Walk-forward and momentum backtest require Pro or higher.",
        "required_capability": "walk_forward_report",
        "timestamp": _ts(),
    }


def check_fortress_access(plan: Plan) -> Optional[Dict[str, Any]]:
    v = check_license_valid(plan)
    if v:
        return v
    if fortress_allowed(plan.tier):
        return None
    return {
        "error": "tier_gate",
        "feature": "fortress",
        "tier": plan.tier,
        "message": "Fortress hedging requires Pro or higher.",
        "required_capability": "fortress_hedging",
        "timestamp": _ts(),
    }


def check_trust_export_access(plan: Plan) -> Optional[Dict[str, Any]]:
    v = check_license_valid(plan)
    if v:
        return v
    if trust_ledger_export_allowed(plan.tier):
        return None
    return {
        "error": "tier_gate",
        "feature": "trust_export",
        "tier": plan.tier,
        "message": "Audit bundle export requires Pro or higher.",
        "required_capability": "trust_ledger_export",
        "timestamp": _ts(),
    }


def gated_walk_forward_stub() -> Dict[str, Any]:
    return {
        "timestamp": _ts(),
        "gated": True,
        "reason": "tier_gate",
        "message": "Walk-forward report requires Pro or higher.",
    }


def gated_backtest_stub() -> Dict[str, Any]:
    return {
        "timestamp": _ts(),
        "gated": True,
        "message": "Backtest snapshot requires Pro or higher.",
    }


def gated_research_verdict_stub() -> Dict[str, Any]:
    return {
        "verdict": "gated",
        "headline": "Research verdict requires Pro or higher (walk-forward / backtest).",
        "timestamp": _ts(),
    }


# Runbook command ids → gate type
_RUNBOOK_GATES = {
    "run_fortress_now": "fortress",
    "walk_forward_refresh": "backtest",
    "export_audit_bundle": "trust_export",
}


def filter_runbooks_for_plan(items: List[dict], plan: Plan) -> List[dict]:
    """Drop or mark runbook entries the current plan cannot run."""
    out: List[dict] = []
    for row in items:
        rid = str(row.get("id") or "")
        gate = _RUNBOOK_GATES.get(rid)
        if not gate:
            out.append(row)
            continue
        denied = None
        if gate == "fortress":
            denied = check_fortress_access(plan)
        elif gate == "backtest":
            denied = check_backtest_access(plan)
        elif gate == "trust_export":
            denied = check_trust_export_access(plan)
        if denied:
            copy = dict(row)
            copy["tier_gated"] = True
            copy["tier_gate_message"] = denied.get("message", "Upgrade required.")
            out.append(copy)
        else:
            out.append(row)
    return out


def deny_cli_json(denied: Dict[str, Any], code: int = 2) -> None:
    """Print JSON error to stderr and exit (for scripts / CLI)."""
    import json
    import sys

    print(json.dumps(denied, indent=2), file=sys.stderr)
    raise SystemExit(code)
