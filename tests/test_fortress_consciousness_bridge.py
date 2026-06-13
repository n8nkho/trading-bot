"""Classic Fortress consciousness bridge tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from utils.fortress_consciousness_bridge import consciousness_audit_appendix, load_consciousness_snapshot


class TestFortressConsciousnessBridge(unittest.TestCase):
    def test_disabled_when_sibling_missing(self):
        with patch("utils.fortress_consciousness_bridge._FORTRESS_AI") as p:
            p.is_dir.return_value = False
            out = load_consciousness_snapshot()
        self.assertFalse(out.get("enabled", True))

    def test_appendix_empty_when_off(self):
        with patch("utils.fortress_consciousness_bridge.load_consciousness_snapshot", return_value={"enabled": False}):
            self.assertEqual(consciousness_audit_appendix(), "")


if __name__ == "__main__":
    unittest.main()
