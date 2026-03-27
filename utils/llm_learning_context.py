"""
Build compact learning context from recent LLM lessons for entry prompts.
"""

from __future__ import annotations

from utils.llm_decision_tracker import get_llm_decision_tracker


def build_learning_context(limit: int = 5) -> str:
    tracker = get_llm_decision_tracker()
    lessons = tracker.get_recent_lessons(limit=limit)
    if not lessons:
        return (
            "LEARNINGS: No prior structured lessons yet. Treat each setup on its own merits; "
            "paper trading is for gathering evidence."
        )
    lines = ["LEARNINGS FROM RECENT CLOSED TRADES (use as hints, not excuses to skip):\n"]
    for i, lesson in enumerate(lessons, 1):
        sym = lesson.get("symbol") or "—"
        learned = lesson.get("lesson_learned") or lesson.get("lesson") or ""
        adj = lesson.get("future_adjustment") or lesson.get("adjustment") or ""
        pat = lesson.get("pattern_discovered") or ""
        lines.append(f"{i}. {sym}: {learned}")
        if adj:
            lines.append(f"   Adjustment: {adj}")
        if pat:
            lines.append(f"   Pattern: {pat}")
        lines.append("")
    lines.append("Prefer acting on aligned signals; refine sizing/confidence using lessons above.\n")
    return "\n".join(lines)
