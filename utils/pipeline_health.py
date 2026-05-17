"""Track consecutive zero-candidate screening runs for operator alerts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json, write_json_atomic

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "screening_pipeline_health.json"


def record_screening_outcome(*, candidates_found: int) -> dict[str, Any]:
    doc = read_json(_PATH, default={})
    if not isinstance(doc, dict):
        doc = {}
    prev = int(doc.get("consecutive_zero_runs") or 0)
    if int(candidates_found) <= 0:
        consecutive = prev + 1
    else:
        consecutive = 0
    out = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_candidates_found": int(candidates_found),
        "consecutive_zero_runs": consecutive,
    }
    if consecutive >= 3:
        out["operator_warn"] = (
            "3+ consecutive screening runs with 0 candidates — review prefilter thresholds and watchlist."
        )
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(_PATH, {**doc, **out})
    return out
