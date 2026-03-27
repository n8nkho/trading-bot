#!/usr/bin/env python3
"""
Comprehensive LLM Learning System Integration Test.

Uses the real tracker API: record_outcome(signal_id, outcome) after link_signal(decision_id, signal_id).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_1_files_exist() -> bool:
    """Test 1: Verify decision and lesson files exist (or are creatable under data/)."""
    print("\n" + "=" * 70)
    print("TEST 1: File Creation")
    print("=" * 70)

    files = ["data/llm_decisions.jsonl", "data/llm_lessons.jsonl"]
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ok = True
    for rel in files:
        p = ROOT / rel
        if not p.exists():
            p.touch()
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        status = "OK" if exists else "FAIL"
        print(f"[{status}] {rel}: {'exists' if exists else 'MISSING'} ({size} bytes)")
        ok = ok and exists
    return ok


def test_2_decision_tracker() -> bool:
    """Test 2: Decision tracker record_decision -> link_signal -> record_outcome."""
    print("\n" + "=" * 70)
    print("TEST 2: Decision Tracker")
    print("=" * 70)

    try:
        import utils.llm_decision_tracker as mod

        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            monkey_dec = tdir / "llm_decisions.jsonl"
            monkey_les = tdir / "llm_lessons.jsonl"
            mod.DECISIONS_FILE = monkey_dec
            mod.LESSONS_FILE = monkey_les
            mod._tracker = None

            tracker = mod.get_llm_decision_tracker()
            print("OK LLMDecisionTracker (via get_llm_decision_tracker) ready")

            decision = {
                "decision": "BUY",
                "confidence": 0.78,
                "reasoning": "Strong technical signals with analyst support",
                "key_factors": ["oversold_rsi", "volume_spike", "analyst_buy"],
                "expected_outcome": "+3% mean reversion",
                "position_size_multiplier": 1.0,
            }
            candidate = {
                "ticker": "TEST",
                "current_price": 100.0,
                "rsi": 32.5,
                "volume_ratio": 2.1,
                "analyst_rec": "BUY",
                "scout_score": 0.65,
            }

            decision_id = tracker.record_decision("TEST", decision, candidate)
            assert isinstance(decision_id, str) and decision_id
            print(f"OK Decision recorded, decision_id={decision_id}")

            signal_id = "TEST_SIG_INTEGRATION_001"
            assert tracker.link_signal(decision_id, signal_id)
            print(f"OK link_signal -> signal_id={signal_id}")

            outcome = {
                "pnl": 150.0,
                "pnl_pct": 3.2,
                "duration_hours": 4.5,
                "exit_reason": "TAKE_PROFIT",
                "exit_price": 103.20,
            }
            success = tracker.record_outcome(signal_id, outcome)
            print(f"OK record_outcome(signal_id): {success}")
            assert success

            pending = tracker.get_pending_with_outcomes(limit=5)
            print(f"OK get_pending_with_outcomes: {len(pending)} row(s)")

        from utils.llm_learning_context import build_learning_context

        ctx = build_learning_context(limit=3)
        print(f"OK build_learning_context ({len(ctx)} chars)")
        return True

    except Exception as e:
        print(f"FAIL Decision tracker test: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_3_learning_agent() -> bool:
    """Test 3: Learning agent daily review (no LLM call required for empty state)."""
    print("\n" + "=" * 70)
    print("TEST 3: Learning Agent")
    print("=" * 70)

    try:
        from agents.llm_learning_agent import LLMLearningAgent

        learner = LLMLearningAgent()
        print("OK LLMLearningAgent imported")
        out = learner.daily_learning_review()
        print(f"OK daily_learning_review: {out.get('message', out)}")
        return True

    except Exception as e:
        print(f"FAIL Learning agent test: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_4_learning_context() -> bool:
    """Test 4: Learning context builder."""
    print("\n" + "=" * 70)
    print("TEST 4: Learning Context")
    print("=" * 70)

    try:
        from utils.llm_learning_context import build_learning_context

        context = build_learning_context()
        print("OK Learning context built")
        preview = context[:500] + ("..." if len(context) > 500 else "")
        print(f"\nContext preview:\n{preview}")
        return True

    except Exception as e:
        print(f"FAIL Learning context test: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_5_entry_integration() -> bool:
    """Test 5: Entry agent integration check."""
    print("\n" + "=" * 70)
    print("TEST 5: Entry Agent Integration")
    print("=" * 70)

    try:
        path = ROOT / "agents" / "entry_agent.py"
        content = path.read_text(encoding="utf-8")
        has_tracker = "get_llm_decision_tracker" in content
        has_record = "record_decision" in content
        print(f"{'OK' if has_tracker else 'FAIL'} entry_agent uses get_llm_decision_tracker: {has_tracker}")
        print(f"{'OK' if has_record else 'FAIL'} entry_agent calls record_decision: {has_record}")
        return has_tracker and has_record

    except Exception as e:
        print(f"FAIL Entry integration check: {e}")
        return False


def test_6_exit_integration() -> bool:
    """Test 6: Exit monitor + orchestrator outcome wiring."""
    print("\n" + "=" * 70)
    print("TEST 6: Exit Monitor Integration")
    print("=" * 70)

    try:
        em = (ROOT / "agents" / "exit_monitor.py").read_text(encoding="utf-8")
        orch = (ROOT / "orchestrator.py").read_text(encoding="utf-8")

        has_fn = "record_llm_outcome_after_sell_all_fill" in em
        has_record = "record_outcome" in em
        has_tracker = "get_llm_decision_tracker" in em
        orch_calls = "record_llm_outcome_after_sell_all_fill" in orch

        print(f"{'OK' if has_fn else 'FAIL'} exit_monitor defines record_llm_outcome_after_sell_all_fill: {has_fn}")
        print(f"{'OK' if has_record else 'FAIL'} exit_monitor calls record_outcome: {has_record}")
        print(f"{'OK' if has_tracker else 'FAIL'} exit_monitor uses get_llm_decision_tracker: {has_tracker}")
        print(f"{'OK' if orch_calls else 'FAIL'} orchestrator invokes record_llm_outcome_after_sell_all_fill: {orch_calls}")
        n = em.count("record_outcome")
        print(f"OK record_outcome occurrences in exit_monitor.py: {n}")
        return has_fn and has_record and has_tracker and orch_calls

    except Exception as e:
        print(f"FAIL Exit integration check: {e}")
        return False


def test_7_evolution_integration() -> bool:
    """Test 7: Evolution cycle includes LLM learning review."""
    print("\n" + "=" * 70)
    print("TEST 7: Evolution Cycle Integration")
    print("=" * 70)

    try:
        import inspect

        from agents.recursive_evolution import run_recursive_evolution

        source = inspect.getsource(run_recursive_evolution)
        has_learning = "llm_learning_review" in source
        print(f"{'OK' if has_learning else 'FAIL'} run_recursive_evolution includes llm_learning_review: {has_learning}")
        return has_learning

    except Exception as e:
        print(f"FAIL Evolution integration check: {e}")
        import traceback

        traceback.print_exc()
        return False


def main() -> int:
    os.chdir(ROOT)
    print("\n" + "=" * 70)
    print("COMPREHENSIVE LLM LEARNING SYSTEM INTEGRATION TEST")
    print("=" * 70)

    tests = [
        ("Files Exist", test_1_files_exist),
        ("Decision Tracker", test_2_decision_tracker),
        ("Learning Agent", test_3_learning_agent),
        ("Learning Context", test_4_learning_context),
        ("Entry Integration", test_5_entry_integration),
        ("Exit Integration", test_6_exit_integration),
        ("Evolution Integration", test_7_evolution_integration),
    ]

    results: list[tuple[str, bool]] = []
    for name, fn in tests:
        try:
            results.append((name, fn()))
        except Exception as e:
            print(f"\nFAIL {name} crashed: {e}")
            results.append((name, False))

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")

    print(f"\nTotal: {passed}/{total} tests passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
