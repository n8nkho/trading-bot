from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.analysts.consensus import run_analyst_ensemble


class TestAnalystConsensus(unittest.TestCase):
    def test_consensus_output(self):
        with TemporaryDirectory() as td:
            out = run_analyst_ensemble(
                opportunities=[{"symbol": "AAPL", "score": 0.7, "theme": "macro"}],
                data_dir=Path(td),
            )
            self.assertEqual(out["analyst_count"], 4)
            self.assertEqual(out["evaluated"], 1)
            self.assertEqual(out["recommendations"][0]["symbol"], "AAPL")


if __name__ == "__main__":
    unittest.main()

