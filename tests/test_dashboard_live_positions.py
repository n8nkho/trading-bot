import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class DashboardLivePositionsTest(unittest.TestCase):
    def test_empty_broker_positions_do_not_fall_back_to_stale_file(self):
        import dashboard.command_center as command_center

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            (data_dir / "positions.json").write_text(
                json.dumps(
                    [
                        {
                            "ticker": "AAPL",
                            "qty": 10,
                            "entry_price": 100,
                            "current_price": 110,
                        }
                    ]
                ),
                encoding="utf-8",
            )

            fake_broker = types.ModuleType("utils.alpaca_broker")
            fake_broker.fetch_broker_positions = lambda: ([], None)
            fake_yfinance = types.ModuleType("yfinance")

            original_data_dir = command_center.DATA_DIR
            command_center.DATA_DIR = data_dir
            try:
                with patch.dict(
                    sys.modules,
                    {"utils.alpaca_broker": fake_broker, "yfinance": fake_yfinance},
                ):
                    result = command_center.get_live_positions()
            finally:
                command_center.DATA_DIR = original_data_dir

        self.assertEqual(result["positions"], [])
        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()
