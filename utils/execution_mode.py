"""
Fortress execution mode: autonomous broker submission vs human-in-the-loop queue.

Set ``FORTRESS_EXECUTION_MODE`` in the environment (see ``.env.example``).
"""

from __future__ import annotations

import os

_HUMAN_ALIASES = frozenset(
    {"human_in_loop", "human", "hitl", "manual", "manual_approval"}
)


def get_execution_mode() -> str:
    """
    Return ``autonomous`` or ``human_in_loop``.

    - **autonomous** — daily screening / intraday sniper may submit orders when
      candidates pass risk and pre-trade gates.
    - **human_in_loop** — approved entries are written to
      ``data/pending_execution_queue.json``; operator runs
      ``python orchestrator.py execute_pending`` after review.
    """
    raw = (os.getenv("FORTRESS_EXECUTION_MODE") or "autonomous").strip().lower()
    if raw in _HUMAN_ALIASES:
        return "human_in_loop"
    return "autonomous"


def is_human_in_loop() -> bool:
    return get_execution_mode() == "human_in_loop"
