from __future__ import annotations

import unittest
from datetime import date

from agents.geographic_executor import _is_first_monday_window
from agents.sector_executor import _is_first_trading_day_of_month


class TestAllocationExecutors(unittest.TestCase):
    def test_first_trading_day_of_month(self):
        self.assertTrue(_is_first_trading_day_of_month(date(2026, 6, 1)))  # Monday
        self.assertFalse(_is_first_trading_day_of_month(date(2026, 6, 2)))

    def test_first_monday_window(self):
        self.assertTrue(_is_first_monday_window(date(2026, 6, 1)))
        self.assertFalse(_is_first_monday_window(date(2026, 6, 8)))
        self.assertFalse(_is_first_monday_window(date(2026, 6, 2)))


if __name__ == "__main__":
    unittest.main()

