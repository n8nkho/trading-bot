from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


class TestExitMonitorOptionExpiryHandling(unittest.TestCase):
    def test_expired_option_skips_chain_lookup(self):
        from agents.exit_monitor import check_option_exit

        position = {
            "ticker": "AAPL260101C00100000",
            "underlying_ticker": "AAPL",
            "entry_premium": 1.25,
            "qty": 1,
            "strike": 100.0,
            "call": True,
            "expiration_date": (datetime.now() - timedelta(days=1)).date().isoformat(),
        }

        with patch("agents.exit_monitor._get_option_chain") as mock_chain:
            decision = check_option_exit(position)

        self.assertEqual(decision["action"], "HOLD")
        self.assertIn("Expired option contract", decision["reason"])
        mock_chain.assert_not_called()

    def test_unavailable_expiration_cached_after_first_failure(self):
        from agents import exit_monitor as mod

        # Ensure isolation across test runs.
        mod._INVALID_OPTION_EXPIRATIONS.clear()
        position = {
            "ticker": "AAPL260630C00100000",
            "underlying_ticker": "AAPL",
            "entry_premium": 1.25,
            "qty": 1,
            "strike": 100.0,
            "call": True,
            "expiration_date": (datetime.now() + timedelta(days=60)).date().isoformat(),
        }

        err = ValueError("Expiration `2099-01-01` cannot be found. Available expirations are: [2026-05-01]")
        with patch("agents.exit_monitor._get_option_chain", side_effect=err) as mock_chain:
            first = mod.check_option_exit(position)
            second = mod.check_option_exit(position)

        self.assertEqual(first["action"], "HOLD")
        self.assertIn("Expiration unavailable in chain", first["reason"])
        self.assertEqual(second["action"], "HOLD")
        self.assertIn("Expiration unavailable in chain", second["reason"])
        self.assertEqual(mock_chain.call_count, 1)

    def test_monitor_positions_coalesces_duplicate_option_contracts(self):
        from agents import exit_monitor as mod

        positions = [
            {
                "type": "OPTION",
                "ticker": "AAPL260630C00100000",
                "underlying_ticker": "AAPL",
                "entry_premium": 1.0,
                "qty": 1,
                "strike": 100.0,
                "call": True,
                "expiration_date": (datetime.now() + timedelta(days=60)).date().isoformat(),
            },
            {
                "type": "OPTION",
                "ticker": "AAPL260630C00100000",
                "underlying_ticker": "AAPL",
                "entry_premium": 1.0,
                "qty": 2,
                "strike": 100.0,
                "call": True,
                "expiration_date": (datetime.now() + timedelta(days=60)).date().isoformat(),
            },
        ]

        captured_qty = {"value": 0}

        def _fake_check_option_exit(pos):
            captured_qty["value"] = int(pos.get("qty") or 0)
            return {"ticker": pos["ticker"], "action": "HOLD", "reason": "ok"}

        with patch("agents.exit_monitor.check_option_exit", side_effect=_fake_check_option_exit) as mocked:
            out = mod.monitor_positions(positions)

        self.assertEqual(len(out), 1)
        self.assertEqual(captured_qty["value"], 3)
        self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
