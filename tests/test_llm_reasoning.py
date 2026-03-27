from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.llm_reasoning_engine import LLMReasoningEngine


class TestLlmReasoningEngine(unittest.TestCase):
    def test_trade_evaluation_parses_json(self):
        engine = LLMReasoningEngine()
        with patch("agents.llm_reasoning_engine.call_llm", return_value='{"decision":"BUY","confidence":0.82,"reasoning":"setup strong","position_size_multiplier":1.2}'):
            decision = engine.evaluate_trade_opportunity(
                {
                    "ticker": "TEST",
                    "current_price": 100.0,
                    "rsi": 35,
                    "volume_ratio": 2.0,
                    "drop_pct": -3.0,
                }
            )
        self.assertEqual(decision["decision"], "BUY")
        self.assertTrue(decision["llm_available"])
        self.assertGreaterEqual(decision["confidence"], 0.8)

    def test_exit_evaluation_fallback_when_invalid_json(self):
        engine = LLMReasoningEngine()
        with patch("agents.llm_reasoning_engine.call_llm", return_value="not json"):
            decision = engine.evaluate_exit(
                {"ticker": "TEST", "entry_price": 100.0, "current_price": 98.0, "pnl_pct": -2.0, "days_held": 1, "qty": 10}
            )
        self.assertEqual(decision["decision"], "HOLD")
        self.assertFalse(decision["llm_available"])


if __name__ == "__main__":
    unittest.main()

