from __future__ import annotations

import unittest

from agents.cio_agent import _derive_directive


class TestCioAgent(unittest.TestCase):
    def test_directive_derivation(self):
        self.assertEqual(_derive_directive("RISK_OFF", 28.0)[0], "DEFENSIVE")
        self.assertEqual(_derive_directive("RISK_ON", 14.0)[0], "OFFENSIVE")
        self.assertEqual(_derive_directive("UNKNOWN", 24.0)[0], "BALANCED")


if __name__ == "__main__":
    unittest.main()

