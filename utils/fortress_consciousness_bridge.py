"""Read fortress-ai market consciousness from classic Fortress sibling repo."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_FORTRESS_AI = Path(os.environ.get("FORTRESS_AI_ROOT", "/home/ubuntu/fortress-ai"))


def consciousness_bridge_enabled() -> bool:
    return str(os.environ.get("FORTRESS_CLASSIC_CONSCIOUSNESS", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def load_consciousness_snapshot() -> dict[str, Any]:
    if not consciousness_bridge_enabled() or not _FORTRESS_AI.is_dir():
        return {"enabled": False, "skipped": "sibling_unavailable"}
    try:
        root = str(_FORTRESS_AI)
        if root not in sys.path:
            sys.path.insert(0, root)
        from utils.market_consciousness import consciousness_dashboard_snapshot

        return consciousness_dashboard_snapshot()
    except Exception as e:
        return {"enabled": False, "error": str(e)[:120]}


def consciousness_audit_appendix() -> str:
    snap = load_consciousness_snapshot()
    if not snap.get("enabled"):
        return ""
    compact = {
        "session_intent": (snap.get("session_intent") or {}).get("plan_line"),
        "posture": (snap.get("consciousness_posture") or {}).get("mode"),
        "alpha_vs_spy_pct": (snap.get("self_state") or {}).get("alpha_vs_spy_pct"),
        "analogue_day_summary": snap.get("analogue_day_summary"),
        "events": (snap.get("market_events") or {}).get("events"),
    }
    return "FORTRESS_CONSCIOUSNESS: " + json.dumps(compact, separators=(",", ":"), default=str)[:800]
