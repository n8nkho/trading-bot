"""
Review LLM entry decisions vs realized outcomes and persist lessons (paper trading).
Uses the configured LLM provider (DeepSeek/Ollama) via utils.local_llm.call_llm.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from utils.local_llm import call_llm
from utils.llm_decision_tracker import get_llm_decision_tracker

logger = logging.getLogger(__name__)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


SYSTEM_LESSON = """You review a single past paper trade where an LLM chose BUY or SKIP.
Output ONLY valid JSON with keys:
prediction_accuracy ("accurate" or "inaccurate"),
what_worked (string),
what_failed (string),
lesson_learned (string),
future_adjustment (string),
pattern_discovered (string or null),
confidence_calibration (string)."""


class LLMLearningAgent:
    def __init__(self) -> None:
        self.tracker = get_llm_decision_tracker()

    def learn_from_trade(self, decision_record: dict[str, Any]) -> dict[str, Any] | None:
        if not decision_record.get("outcome"):
            return None
        symbol = decision_record.get("symbol") or ""
        decision = decision_record.get("decision") if isinstance(decision_record.get("decision"), dict) else {}
        outcome = decision_record["outcome"]
        pnl = float(outcome.get("pnl") or outcome.get("pnl_dollars") or 0.0)
        pnl_pct = float(outcome.get("pnl_pct") or 0.0)

        user = json.dumps(
            {
                "symbol": symbol,
                "llm_decision": decision,
                "candidate_data": decision_record.get("candidate_data"),
                "outcome": {
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "duration_hours": outcome.get("duration_hours"),
                    "exit_reason": outcome.get("exit_reason"),
                    "exit_price": outcome.get("exit_price"),
                },
            },
            default=str,
            indent=2,
        )
        prompt = f"{SYSTEM_LESSON}\n\nTRADE RECORD:\n{user}"
        raw = call_llm(prompt, timeout=60)
        parsed = _extract_json_object(raw)
        if not parsed:
            logger.info("Learning agent: no parseable JSON from LLM")
            return None
        parsed["symbol"] = symbol
        parsed["timestamp"] = datetime.now().isoformat()
        parsed["source_decision_id"] = decision_record.get("decision_id")
        self.tracker.save_lesson(parsed)
        if decision_record.get("decision_id"):
            self.tracker.mark_lesson_extracted(str(decision_record["decision_id"]))
        return parsed

    def daily_learning_review(self, max_trades: int = 25) -> dict[str, Any]:
        recent = self.tracker.get_recent_decisions(limit=200)
        with_out = [d for d in recent if d.get("outcome") is not None and not d.get("lesson_extracted")]
        if not with_out:
            return {"reviewed": 0, "lessons": 0, "message": "No completed LLM-tracked trades yet."}

        lessons: list[dict[str, Any]] = []
        for rec in with_out[-max_trades:]:
            try:
                le = self.learn_from_trade(rec)
                if le:
                    lessons.append(le)
            except Exception as e:
                logger.warning("learn_from_trade failed: %s", e)

        accurate = sum(1 for l in lessons if str(l.get("prediction_accuracy", "")).lower() == "accurate")
        return {
            "reviewed": len(with_out[-max_trades:]),
            "lessons": len(lessons),
            "accurate_count": accurate,
            "inaccurate_count": max(0, len(lessons) - accurate),
        }


def main() -> None:
    agent = LLMLearningAgent()
    out = agent.daily_learning_review()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
