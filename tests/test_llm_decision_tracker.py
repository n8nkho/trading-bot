from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_llm_decision_tracker_link_and_outcome(tmp_path, monkeypatch):
    import utils.llm_decision_tracker as mod

    monkeypatch.setattr(mod, "DECISIONS_FILE", tmp_path / "llm_decisions.jsonl")
    monkeypatch.setattr(mod, "LESSONS_FILE", tmp_path / "llm_lessons.jsonl")
    mod._tracker = None

    tr = mod.get_llm_decision_tracker()
    did = tr.record_decision(
        "TEST",
        {"decision": "BUY", "confidence": 0.8, "reasoning": "x"},
        {"rsi": 35, "current_price": 10.0},
    )
    assert did
    assert tr.link_signal(did, "TEST_20260101_120000")
    out = {"pnl": 12.0, "pnl_pct": 1.5, "exit_reason": "test", "exit_price": 10.1}
    assert tr.record_outcome("TEST_20260101_120000", out)
    row = tr.get_decision_by_signal("TEST_20260101_120000")
    assert row is not None
    assert row["outcome"]["pnl"] == 12.0
