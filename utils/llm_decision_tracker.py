"""
Track LLM entry decisions and outcomes for recursive learning (paper trading).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DECISIONS_FILE = DATA_DIR / "llm_decisions.jsonl"
LESSONS_FILE = DATA_DIR / "llm_lessons.jsonl"


def _read_all_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError as e:
        logger.warning("Could not read %s: %s", path, e)
    return rows


def _write_all_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


class LLMDecisionTracker:
    """
    Append-only log with in-place updates for outcome / signal_id linkage.
    """

    def __init__(self) -> None:
        self.decisions_file = DECISIONS_FILE
        self.lessons_file = LESSONS_FILE

    def record_decision(
        self,
        symbol: str,
        decision: dict[str, Any],
        candidate: dict[str, Any],
    ) -> str:
        decision_id = str(uuid.uuid4())
        record: dict[str, Any] = {
            "decision_id": decision_id,
            "timestamp": datetime.now().isoformat(),
            "symbol": str(symbol).upper(),
            "decision": decision,
            "candidate_data": {
                "price": candidate.get("price") or candidate.get("current_price"),
                "rsi": candidate.get("rsi"),
                "volume_ratio": candidate.get("volume_ratio"),
                "drop_pct": candidate.get("drop_pct"),
                "analyst_rec": (candidate.get("analyst_meta") or {}).get("recommendation")
                if isinstance(candidate.get("analyst_meta"), dict)
                else candidate.get("analyst_rec"),
                "scout_score": (candidate.get("agentic_meta") or {}).get("scout_score")
                if isinstance(candidate.get("agentic_meta"), dict)
                else candidate.get("scout_score"),
            },
            "signal_id": None,
            "outcome": None,
        }
        try:
            with open(self.decisions_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError as e:
            logger.warning("Could not append llm decision: %s", e)
        return decision_id

    def link_signal(self, decision_id: str, signal_id: str) -> bool:
        rows = _read_all_jsonl(self.decisions_file)
        updated = False
        for row in rows:
            if row.get("decision_id") == decision_id:
                row["signal_id"] = signal_id
                updated = True
                break
        if updated:
            _write_all_jsonl(self.decisions_file, rows)
        return updated

    def record_outcome(self, signal_id: str, outcome: dict[str, Any]) -> bool:
        rows = _read_all_jsonl(self.decisions_file)
        updated = False
        for row in rows:
            if row.get("signal_id") != signal_id:
                continue
            if row.get("outcome") is not None:
                continue
            dec = row.get("decision") if isinstance(row.get("decision"), dict) else {}
            if str(dec.get("decision") or "").upper() != "BUY":
                continue
            row["outcome"] = outcome
            row["outcome_timestamp"] = datetime.now().isoformat()
            updated = True
            break
        if updated:
            _write_all_jsonl(self.decisions_file, rows)
        return updated

    def get_recent_decisions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = _read_all_jsonl(self.decisions_file)
        return rows[-limit:]

    def get_pending_with_outcomes(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = _read_all_jsonl(self.decisions_file)
        return [r for r in rows if r.get("outcome") is not None][-limit:]

    def save_lesson(self, lesson: dict[str, Any]) -> None:
        lesson = dict(lesson)
        lesson.setdefault("timestamp", datetime.now().isoformat())
        try:
            with open(self.lessons_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(lesson, default=str) + "\n")
        except OSError as e:
            logger.warning("Could not append lesson: %s", e)

    def get_recent_lessons(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = _read_all_jsonl(self.lessons_file)
        return rows[-limit:]

    def get_decision_by_signal(self, signal_id: str) -> dict[str, Any] | None:
        for row in reversed(_read_all_jsonl(self.decisions_file)):
            if row.get("signal_id") == signal_id:
                return row
        return None

    def mark_lesson_extracted(self, decision_id: str) -> bool:
        rows = _read_all_jsonl(self.decisions_file)
        updated = False
        for row in rows:
            if row.get("decision_id") == decision_id:
                row["lesson_extracted"] = True
                updated = True
                break
        if updated:
            _write_all_jsonl(self.decisions_file, rows)
        return updated


_tracker: LLMDecisionTracker | None = None


def get_llm_decision_tracker() -> LLMDecisionTracker:
    global _tracker
    if _tracker is None:
        _tracker = LLMDecisionTracker()
    return _tracker
