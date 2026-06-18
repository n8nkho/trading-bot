"""Order sizer tests."""
from __future__ import annotations

import unittest
from unittest import mock

from utils.order_sizer import chunk_qtys, plan_chunked_exit, submit_chunked_sell_orders


class TestOrderSizer(unittest.TestCase):
    def test_chunk_qtys_splits_large_exit(self):
        chunks = chunk_qtys(447, px=200.0, max_notional_usd=3000.0)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(sum(chunks), 447)
        self.assertTrue(all(c * 200.0 <= 3000.0 for c in chunks))

    def test_plan_chunked_exit_flags_chunks(self):
        plan = plan_chunked_exit(447, 200.0)
        self.assertTrue(plan.get("chunked_exit"))
        self.assertEqual(sum(plan.get("order_qtys") or []), 447)

    def test_submit_chunked_sell_orders(self):
        calls: list[int] = []

        def submit_one(_ticker: str, qty: int) -> dict:
            calls.append(qty)
            return {"success": True, "order_id": f"o{qty}", "filled_qty": qty, "filled_price": 10.0}

        with mock.patch.dict("os.environ", {"FORTRESS_MAX_ORDER_NOTIONAL_USD": "3000"}):
            out = submit_chunked_sell_orders("IBM", 447, 200.0, submit_one=submit_one)
        self.assertTrue(out.get("success"))
        self.assertTrue(out.get("chunked_exit"))
        self.assertEqual(sum(calls), 447)


if __name__ == "__main__":
    unittest.main()
