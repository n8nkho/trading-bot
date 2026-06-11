"""Phase 2 — Classic gate parity, broker brackets, risk_guardian state safety."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestClassicGateParity(unittest.TestCase):
    def setUp(self):
        os.environ["FORTRESS_REGIME_STALE_BLOCK_RTH"] = "0"
        os.environ["FORTRESS_HEDGE_ERROR_BLOCK_ENTRIES"] = "0"

    def tearDown(self):
        os.environ.pop("FORTRESS_REGIME_STALE_BLOCK_RTH", None)
        os.environ.pop("FORTRESS_HEDGE_ERROR_BLOCK_ENTRIES", None)
        os.environ.pop("FORTRESS_POSITION_SIZE_PCT", None)

    def test_buy_blocked_when_notional_exceeds_equity_times_pct(self):
        from utils.pre_trade_gate import evaluate_pre_trade_submission

        g = evaluate_pre_trade_submission(
            side="BUY",
            symbol="AAPL",
            qty=100,
            estimated_notional_usd=5000.0,
            portfolio_equity_usd=100000.0,
        )
        self.assertFalse(g["allowed"])
        self.assertTrue(any("estimated_notional_exceeds_cap" in r for r in g["reasons"]))

    def test_sell_passes_estimated_notional(self):
        from utils.pre_trade_gate import evaluate_pre_trade_submission

        os.environ["FORTRESS_MAX_ORDER_NOTIONAL_USD"] = "50"
        try:
            g = evaluate_pre_trade_submission(
                side="SELL",
                symbol="AAPL",
                qty=10,
                estimated_notional_usd=999.0,
            )
            self.assertFalse(g["allowed"])
        finally:
            os.environ.pop("FORTRESS_MAX_ORDER_NOTIONAL_USD", None)


class TestClassicBracketExecution(unittest.TestCase):
    def test_classic_bracket_prices_percent_points(self):
        from utils.alpaca_execution import classic_bracket_prices

        tp, sl = classic_bracket_prices(entry_price=100.0, stop_loss_pct=-2.0, take_profit_pct=15.0)
        self.assertEqual(tp, 115.0)
        self.assertEqual(sl, 98.0)

    def test_submit_bracket_uses_order_class(self):
        from utils.alpaca_execution import submit_entry_with_bracket

        client = MagicMock()
        order = MagicMock()
        order.id = "oid-1"
        order.status = "accepted"
        order.filled_qty = None
        order.filled_avg_price = None
        client.submit_order.return_value = order

        with patch.dict(os.environ, {"FORTRESS_BRACKET_EXITS": "1"}):
            out = submit_entry_with_bracket(
                client=client,
                symbol="AAPL",
                qty=1,
                entry_price=100.0,
                stop_loss_pct=-2.0,
                take_profit_pct=5.0,
            )
        self.assertTrue(out["success"])
        self.assertEqual(out["order_type"], "bracket_market")
        req = client.submit_order.call_args[0][0]
        from alpaca.trading.enums import OrderClass

        self.assertEqual(getattr(req, "order_class", None), OrderClass.BRACKET)

    def test_bracket_failure_skips_naked_market_order(self):
        from utils.alpaca_execution import submit_entry_with_bracket

        client = MagicMock()
        client.submit_order.side_effect = RuntimeError("broker rejected bracket")

        with patch.dict(os.environ, {"FORTRESS_BRACKET_EXITS": "1"}):
            out = submit_entry_with_bracket(
                client=client,
                symbol="AAPL",
                qty=1,
                entry_price=100.0,
                stop_loss_pct=-2.0,
                take_profit_pct=5.0,
            )

        self.assertFalse(out["success"])
        self.assertTrue(out.get("blocked"))
        self.assertEqual(out.get("held"), "SI-HOLD: bracket_unavailable")
        self.assertIn("SI-HOLD: bracket_unavailable", out.get("error") or "")
        self.assertEqual(client.submit_order.call_count, 3)
        for call in client.submit_order.call_args_list:
            req = call[0][0]
            self.assertNotEqual(getattr(req, "order_type", None), "market_fallback")
            order_class = getattr(req, "order_class", None)
            if order_class is not None:
                from alpaca.trading.enums import OrderClass

                self.assertEqual(order_class, OrderClass.BRACKET)


class TestRiskGuardianStateSafety(unittest.TestCase):
    def _reload_rg(self):
        if "agents.risk_guardian" in sys.modules:
            del sys.modules["agents.risk_guardian"]
        return __import__("agents.risk_guardian", fromlist=["risk_guardian"])

    def test_syncs_consecutive_losses_from_disk(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir(parents=True)
            (root / "data" / "risk_guardian_state.json").write_text(
                json.dumps(
                    {
                        "consecutive_losses": 4,
                        "circuit_breaker_active": False,
                        "position_size_reduction": 0.5,
                        "updated_at": "2026-06-01T12:00:00",
                    }
                ),
                encoding="utf-8",
            )
            old = os.getcwd()
            try:
                os.chdir(root)
                rg = self._reload_rg()
                status = rg.get_risk_status()
                self.assertEqual(status["consecutive_losses"], 4)
                cb = rg.check_circuit_breaker()
                self.assertTrue(cb["approved"])
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
