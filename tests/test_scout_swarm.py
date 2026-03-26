from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.scouts.swarm import run_scout_swarm


class TestScoutSwarm(unittest.TestCase):
    def test_swarm_outputs_ranked_queue(self):
        with TemporaryDirectory() as td:
            out = run_scout_swarm(data_dir=Path(td))
            self.assertEqual(out["scout_count"], 5)
            self.assertGreater(out["opportunity_count"], 0)
            self.assertTrue(isinstance(out["opportunities"], list))


if __name__ == "__main__":
    unittest.main()

