"""Auto-resolve stale SI queue items when integrity findings clear."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from utils.si_recommendation_queue import (  # noqa: E402
    DISPOSITION_PENDING_AGENT,
    STATUS_OPEN,
    load_queue,
    process_integrity_scan,
    reconcile_cleared_findings,
    save_queue,
)


class TestSiStaleReconcile(unittest.TestCase):
    def test_reconcile_closes_stale_open_item(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            queue = {
                "version": 1,
                "items": [
                    {
                        "id": "abc",
                        "finding_key": "recursive_evolution:evolution_stale",
                        "status": STATUS_OPEN,
                        "disposition": DISPOSITION_PENDING_AGENT,
                        "source": "integrity_scan",
                        "code": "evolution_stale",
                        "component": "recursive_evolution",
                        "finding": {"code": "evolution_stale", "component": "recursive_evolution"},
                    }
                ],
            }
            with patch("utils.si_recommendation_queue._data_dir", return_value=data):
                save_queue(queue)
                closed = reconcile_cleared_findings({"findings": []})
                self.assertEqual(closed, ["evolution_stale"])
                doc = load_queue()
                self.assertEqual(doc["items"][0]["disposition"], "auto_resolved")

    def test_process_integrity_scan_auto_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            queue = {
                "version": 1,
                "items": [
                    {
                        "id": "abc",
                        "finding_key": "classic_cron:cron_heartbeat_fail",
                        "status": STATUS_OPEN,
                        "disposition": DISPOSITION_PENDING_AGENT,
                        "source": "integrity_scan",
                        "code": "cron_heartbeat_fail",
                        "component": "classic_cron",
                        "finding": {"code": "cron_heartbeat_fail", "component": "classic_cron"},
                    }
                ],
            }
            scan = {"findings": [], "counts": {"critical": 0, "high": 0}}
            with patch("utils.si_recommendation_queue._data_dir", return_value=data):
                save_queue(queue)
                summary = process_integrity_scan(scan)
                self.assertIn("auto_resolved", summary)
                self.assertIn("cron_heartbeat_fail", summary["auto_resolved"])
                self.assertEqual(summary["pending_agent"], [])


if __name__ == "__main__":
    unittest.main()
