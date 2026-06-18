import json
import unittest
from unittest import mock

from agents.meta_architect import evaluate_meta_architect_trigger, _early_trade_floor


class TestMetaArchitectAdaptive(unittest.TestCase):
    def test_default_requires_100(self):
        with mock.patch.dict("os.environ", {"FORTRESS_META_ARCHITECT_ADAPTIVE_ENABLED": "0"}, clear=False):
            t = evaluate_meta_architect_trigger(50)
        self.assertEqual(t["min_trades_required"], 100)
        self.assertFalse(t["early_trigger"])

    def test_adaptive_lowers_floor_when_signals(self):
        env = {
            "FORTRESS_META_ARCHITECT_ADAPTIVE_ENABLED": "1",
            "FORTRESS_META_ARCHITECT_EARLY_TRADE_FLOOR": "30",
            "FORTRESS_META_ARCHITECT_GAP_CYCLES": "3",
        }
        drift_doc = json.dumps({"drift_alert": True, "reason": "degraded"})
        with mock.patch.dict("os.environ", env, clear=False):
            with mock.patch("agents.meta_architect._fortress_capability_gap_streak", return_value=3):
                with mock.patch("builtins.open", mock.mock_open(read_data=drift_doc)):
                    with mock.patch("agents.meta_architect.Path") as mock_path:
                        mock_path.return_value.__truediv__ = lambda self, x: mock_path.return_value
                        mock_path.return_value.read_text.return_value = drift_doc
                        mock_path.return_value.is_file.return_value = True
                        t = evaluate_meta_architect_trigger(40)
        self.assertTrue(t.get("early_trigger") or t["min_trades_required"] == _early_trade_floor())


if __name__ == "__main__":
    unittest.main()
