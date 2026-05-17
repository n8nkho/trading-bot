from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))


class TestCronHeartbeat(unittest.TestCase):
    def test_record_and_evaluate(self):
        from utils import cron_heartbeat as hb

        tmp = Path(__file__).resolve().parent / "_hb_tmp.json"
        if tmp.exists():
            tmp.unlink()
        hb.record_success("screen", path=tmp)
        manifest = [{"job_name": "screen", "expected_interval_minutes": 60}]
        ev = hb.evaluate_heartbeat_health(manifest, store_path=tmp)
        self.assertEqual(ev["overall"], "ok")
        tmp.unlink()


if __name__ == "__main__":
    unittest.main()
