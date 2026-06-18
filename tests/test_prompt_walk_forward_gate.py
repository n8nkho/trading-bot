import json
import os
import unittest
from pathlib import Path
from unittest import mock

from utils.prompt_walk_forward_gate import gate_enabled, promotion_allowed, report_path, run_prompt_walk_forward


class TestPromptWalkForwardGate(unittest.TestCase):
    def test_gate_disabled_allows_promotion(self):
        with mock.patch.dict(os.environ, {"FORTRESS_PROMPT_WF_GATE_ENABLED": "0"}, clear=False):
            ok, reason, _ = promotion_allowed("test-id")
        self.assertTrue(ok)
        self.assertEqual(reason, "gate_disabled")

    def test_gate_blocks_without_report(self):
        with mock.patch.dict(os.environ, {"FORTRESS_PROMPT_WF_GATE_ENABLED": "1"}, clear=False):
            ok, reason, _ = promotion_allowed("missing-report-id")
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_walk_forward_report")

    def test_run_and_pass_stable_report(self, tmp_path=None):
        cid = "unit-test-candidate"
        stable = {
            "stable": True,
            "reason": "evaluated",
            "total_trades": 20,
        }
        with mock.patch("agents.walk_forward_validator.compute_walk_forward_report", return_value=stable):
            with mock.patch("utils.prompt_walk_forward_gate._DATA", Path("data")):
                run_prompt_walk_forward(cid, metadata={"test": True})
        path = report_path(cid)
        if path.is_file():
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc.get("candidate_id"), cid)
            with mock.patch.dict(os.environ, {"FORTRESS_PROMPT_WF_GATE_ENABLED": "1"}, clear=False):
                ok, _, _ = promotion_allowed(cid)
            self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
