"""RTH cron jobs quiet outside session."""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from utils.cron_heartbeat import _job_expected_quiet, _rth_cron_outside_us_session


class TestCronHeartbeatRth(unittest.TestCase):
    def test_weekday_evening_outside_session(self):
        sched = "*/30 9-16 * * 1-5 America/New_York"
        fake = datetime(2026, 5, 20, 20, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("utils.cron_heartbeat.datetime") as mdt:
            mdt.now.return_value = fake
            self.assertTrue(_rth_cron_outside_us_session(sched))
            self.assertTrue(_job_expected_quiet(sched))

    def test_weekday_midday_in_session(self):
        sched = "*/30 9-16 * * 1-5 America/New_York"
        fake = datetime(2026, 5, 20, 11, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("utils.cron_heartbeat.datetime") as mdt:
            mdt.now.return_value = fake
            self.assertFalse(_rth_cron_outside_us_session(sched))


if __name__ == "__main__":
    unittest.main()
