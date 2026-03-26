from __future__ import annotations

import unittest

from agents.day_trading_manager import DayTradingManager
from agents.position_trading_manager import PositionTradingManager
from agents.swing_trading_manager import SwingTradingManager
from utils.strategy_allocation import load_strategy_allocation_config


class TestStrategyAllocationFramework(unittest.TestCase):
    def test_strategy_allocation_config_totals_100(self):
        cfg = load_strategy_allocation_config()
        total = sum(s.capital_allocation_pct for s in cfg.sleeves.values())
        self.assertAlmostEqual(total, 100.0, places=2)
        self.assertIn("day_trading", cfg.sleeves)
        self.assertIn("swing_trading", cfg.sleeves)
        self.assertIn("position_trading", cfg.sleeves)

    def test_managers_return_structured_output(self):
        candidates = [
            {
                "ticker": "AAA",
                "drop_pct": -2.2,
                "rsi": 38.0,
                "volume_ratio": 1.8,
                "analysis": {"confidence": 0.82},
            },
            {
                "ticker": "BBB",
                "drop_pct": -0.5,
                "rsi": 58.0,
                "volume_ratio": 0.9,
                "analysis": {"confidence": 0.45},
            },
        ]
        cfg = load_strategy_allocation_config()
        day = DayTradingManager().evaluate(
            candidates,
            sleeve_cfg=cfg.sleeves["day_trading"].model_dump(),
            regime="MIXED",
            vix=24.0,
            portfolio_value=20_000.0,
        )
        swing = SwingTradingManager().evaluate(
            candidates,
            sleeve_cfg=cfg.sleeves["swing_trading"].model_dump(),
            regime="MIXED",
            vix=24.0,
            portfolio_value=20_000.0,
        )
        pos = PositionTradingManager().evaluate(
            candidates,
            sleeve_cfg=cfg.sleeves["position_trading"].model_dump(),
            regime="MIXED",
            vix=24.0,
            portfolio_value=20_000.0,
        )
        for out in (day, swing, pos):
            self.assertIn("sleeve", out)
            self.assertIn("target_capital_usd", out)
            self.assertIn("selected_candidates", out)
            self.assertIsInstance(out["selected_candidates"], list)


if __name__ == "__main__":
    unittest.main()

