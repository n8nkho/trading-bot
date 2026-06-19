"""Post-screening SI hooks — shared by screener cron and orchestrator screen."""
from __future__ import annotations

from typing import Any


def post_screening_si_hooks(
    *,
    candidates_found: int,
    raw_candidates_found: int | None = None,
    daily_screen: bool = False,
) -> dict[str, Any]:
    """
    Record pipeline health and auto-relax screener/entry when throughput is zero.

    daily_screen=True uses daily_screen_* counters (orchestrator post-RecursiveScreener).
    """
    out: dict[str, Any] = {"candidates_found": int(candidates_found)}
    try:
        from utils.pipeline_health import record_daily_screen_outcome, record_screening_outcome

        if daily_screen:
            out["health"] = record_daily_screen_outcome(
                candidates_found=candidates_found,
                raw_candidates_found=raw_candidates_found,
            )
        else:
            out["health"] = record_screening_outcome(candidates_found=candidates_found)
    except Exception as exc:
        out["health_error"] = str(exc)

    try:
        from utils.classic_si_screener import maybe_auto_relax_screener, reset_relax_on_candidates
        from utils.classic_si_recursive import (
            maybe_auto_relax_recursive,
            reset_relax_on_candidates as reset_recursive_relax,
        )
        from utils.classic_si_entry import maybe_auto_relax_entry_gate

        reset_relax_on_candidates(candidates_found=candidates_found)
        reset_recursive_relax(candidates_found=candidates_found)
        if int(candidates_found) <= 0:
            out["screener_si"] = maybe_auto_relax_screener()
            out["recursive_si"] = maybe_auto_relax_recursive()
            out["entry_si"] = maybe_auto_relax_entry_gate()
    except Exception as exc:
        out["si_error"] = str(exc)

    return out
