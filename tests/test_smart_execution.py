from __future__ import annotations

import unittest

from utils.smart_execution import build_execution_plan


class TestSmartExecution(unittest.TestCase):
    def test_options_limit_when_entry_price_present(self):
        trade = {"trade_type": "OPTION", "ticker": "AAPL", "entry_price": 2.34}
        plan = build_execution_plan(trade, market_open=True)
        self.assertEqual(plan["order_type"], "limit")
        self.assertEqual(plan["limit_price"], 2.34)

    def test_options_market_when_no_entry_price(self):
        trade = {"trade_type": "OPTION", "ticker": "AAPL"}
        plan = build_execution_plan(trade, market_open=True)
        self.assertEqual(plan["order_type"], "market")

    def test_stocks_market_when_market_open(self):
        trade = {"trade_type": "STOCK", "ticker": "SPY", "entry_price": 500.0}
        plan = build_execution_plan(trade, market_open=True)
        self.assertEqual(plan["order_type"], "market")


if __name__ == "__main__":
    unittest.main()

