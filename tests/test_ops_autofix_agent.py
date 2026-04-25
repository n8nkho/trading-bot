from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class TestOpsAutoFixAgent(unittest.TestCase):
    def test_reconcile_stale_runs_dry_run_and_apply(self):
        import utils.run_registry as rr
        from agents import ops_autofix_agent as oa

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            prev_registry = rr.REGISTRY_PATH
            prev_data = oa.DATA_DIR
            prev_logs = oa.LOGS_DIR
            prev_latest = oa.LATEST_REPORT
            try:
                rr.REGISTRY_PATH = tdp / "operational_runs.jsonl"
                oa.DATA_DIR = tdp / "data"
                oa.LOGS_DIR = tdp / "logs"
                oa.LATEST_REPORT = oa.DATA_DIR / "ops_autofix_report_latest.json"

                # Old started run should reconcile; recent one should remain in_progress.
                rr.log_screening_started("old_run", "balanced", 10000.0)
                rr.log_screening_started("new_run", "balanced", 10000.0)

                # Backdate first event timestamp by editing file directly.
                rows = rr.read_recent_operational_events(100)
                rows[0]["timestamp"] = "2000-01-01T00:00:00"
                rr.REGISTRY_PATH.write_text(
                    "".join([json.dumps(r) + "\n" for r in rows]),
                    encoding="utf-8",
                )

                dry = oa.reconcile_stale_screening_runs(stale_after_hours=2.0, dry_run=True)
                self.assertEqual(dry["reconciled_count"], 0)
                self.assertEqual(dry["candidates_count"], 1)

                app = oa.reconcile_stale_screening_runs(stale_after_hours=2.0, dry_run=False)
                self.assertEqual(app["reconciled_count"], 1)
                self.assertEqual(app["reconciled_run_ids"], ["old_run"])
            finally:
                rr.REGISTRY_PATH = prev_registry
                oa.DATA_DIR = prev_data
                oa.LOGS_DIR = prev_logs
                oa.LATEST_REPORT = prev_latest

    def test_dedupe_consecutive_lines_creates_backup(self):
        from agents import ops_autofix_agent as oa

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sniper.log"
            p.write_text("a\nb\nb\nb\nc\nc\nd\n", encoding="utf-8")
            out = oa.dedupe_consecutive_log_lines(p, dry_run=False)
            self.assertTrue(out["changed"])
            self.assertEqual(out["removed"], 3)
            self.assertTrue(out.get("backup_path"))
            txt = p.read_text(encoding="utf-8")
            self.assertEqual(txt.splitlines(), ["a", "b", "c", "d"])


if __name__ == "__main__":
    unittest.main()

