from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class TestUpliftAutoPromote(unittest.TestCase):
    def test_promotes_next_module_after_clean_sessions(self):
        import orchestrator as oc

        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir(parents=True, exist_ok=True)
            status = {
                "version": "2.0",
                "current_phase": "TELEMETRY",
                "feature_flags": {
                    "FORTRESS_UPLIFT_CONVERGENCE_MODE": 2,
                    "FORTRESS_UPLIFT_ADAPTIVE_SIZING_MODE": 1,
                    "FORTRESS_UPLIFT_THROUGHPUT_MODE": 1,
                    "FORTRESS_UPLIFT_EXECUTION_ADVISOR_MODE": 0,
                },
                "rollout_plan": {
                    "sequence": ["convergence", "adaptive_sizing", "throughput", "execution_advisor"],
                    "active_module": "convergence",
                    "next_module": "adaptive_sizing",
                    "soak_min_sessions_per_step": 5,
                },
            }
            (root / "uplift_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            for i in range(5):
                payload = {
                    "timestamp": f"2026-04-3{i}T16:00:00",
                    "entry_gate_summary": {"buy_count": 1, "skip_count": 0},
                    "risk_gate_summary": {"rejected_count": 0},
                    "execution_failures": [],
                }
                (root / "data" / f"daily_signals_2026043{i}.json").write_text(
                    json.dumps(payload, indent=2), encoding="utf-8"
                )
            old_root = oc._ORCHESTRATOR_ROOT
            try:
                oc._ORCHESTRATOR_ROOT = root
                out = oc._promote_next_uplift_module(required_clean_sessions=5, apply=True)
            finally:
                oc._ORCHESTRATOR_ROOT = old_root
            self.assertTrue(out.get("ok"))
            self.assertTrue(out.get("applied"))
            doc = json.loads((root / "uplift_status.json").read_text(encoding="utf-8"))
            self.assertEqual(
                int(doc["feature_flags"]["FORTRESS_UPLIFT_ADAPTIVE_SIZING_MODE"]),
                2,
            )
            self.assertEqual(doc["rollout_plan"]["active_module"], "adaptive_sizing")


if __name__ == "__main__":
    unittest.main()
