"""Cross-stack items must never reach auto-apply or auto-resolve dispositions."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import utils.si_recommendation_queue as sq
from utils.classic_si_autonomous import apply_queued_item, auto_assess_item


def _cross_stack_finding(**overrides):
    base = {
        "code": "classic_fill_recency",
        "component": "classic_fortress",
        "title": "Cross-stack test",
        "recommendation": "Review belief applicability.",
        "severity": "high",
    }
    base.update(overrides)
    return base


class TestCrossStackNeverAutoApplies(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.td = Path(self._tmpdir.name)
        self._patch_queue = mock.patch.object(sq, "queue_path", return_value=self.td / "q.json")
        self._patch_data = mock.patch.object(sq, "_data_dir", return_value=self.td)
        self._patch_queue.start()
        self._patch_data.start()

    def tearDown(self):
        self._patch_data.stop()
        self._patch_queue.stop()
        self._tmpdir.cleanup()

    def _upsert(self, source: str = "fortress_ai_belief") -> dict:
        return sq.upsert_from_finding(_cross_stack_finding(), source=source)

    def _reload(self, item_id: str) -> dict:
        return next(x for x in sq.load_queue()["items"] if x["id"] == item_id)

    def _assert_not_forbidden(self, item: dict, *, context: str) -> None:
        disp = str(item.get("disposition") or "")
        self.assertNotIn(
            disp,
            sq.CROSS_STACK_FORBIDDEN_AUTO_DISPOSITIONS,
            f"{context}: disposition={disp}",
        )

    def test_set_agent_assessment_never_auto_queues(self):
        item = self._upsert()
        with mock.patch.dict(os.environ, {"FORTRESS_CLASSIC_SI_AUTO": "1"}, clear=False):
            updated = sq.set_agent_assessment(item["id"], worth_implementing=True, rationale="test")
        self.assertEqual(updated["disposition"], sq.DISPOSITION_PENDING_HUMAN)
        self.assertTrue(updated.get("requires_human_go"))
        self._assert_not_forbidden(updated, context="set_agent_assessment")

    def test_auto_assess_item_routes_to_human_go(self):
        item = self._upsert(source="capability_review")
        with mock.patch.dict(os.environ, {"FORTRESS_CLASSIC_SI_AUTO": "1"}, clear=False):
            assessed = auto_assess_item(item["id"])
        self.assertEqual(assessed["disposition"], sq.DISPOSITION_PENDING_HUMAN)
        self.assertTrue(assessed.get("requires_human_go"))
        self._assert_not_forbidden(assessed, context="auto_assess_item")

    def test_apply_queued_item_blocked_without_human_go(self):
        item = self._upsert()
        with mock.patch.dict(os.environ, {"FORTRESS_CLASSIC_SI_AUTO": "1"}, clear=False):
            auto_assess_item(item["id"])
            q = sq.load_queue()
            it = next(x for x in q["items"] if x["id"] == item["id"])
            it["disposition"] = sq.DISPOSITION_AUTO_APPLY_QUEUED
            sq.save_queue(q)
            res = apply_queued_item(item["id"])
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("skipped"), "cross_stack_requires_human_go")
        reloaded = self._reload(item["id"])
        self.assertEqual(reloaded["status"], sq.STATUS_OPEN)
        self.assertNotEqual(reloaded["disposition"], sq.DISPOSITION_AUTO_RESOLVED)

    def test_reconcile_cleared_findings_skips_cross_stack(self):
        item = self._upsert(source="capability_review")
        sq.reconcile_cleared_findings({"findings": []})
        reloaded = self._reload(item["id"])
        self.assertEqual(reloaded["status"], sq.STATUS_OPEN)
        self._assert_not_forbidden(reloaded, context="reconcile_cleared_findings")


if __name__ == "__main__":
    unittest.main()
