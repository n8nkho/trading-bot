from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestRecursiveSystem(unittest.TestCase):
    def _seed_min_artifacts(self, data_dir: Path) -> None:
        (data_dir / "analyst_consensus_20260327.json").write_text(
            json.dumps(
                {
                    "recommendations": [
                        {"symbol": "IWM", "recommendation": "BUY", "consensus_score": 0.63},
                        {"symbol": "AAPL", "recommendation": "BUY", "consensus_score": 0.62},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "fortress_intelligence_brief_20260327.json").write_text(
            json.dumps({"qa_checklist": {"critical_blockers": ["sample blocker"]}, "execution_analysis": {"trades_today": {"agentic": 0}}}),
            encoding="utf-8",
        )
        (data_dir / "decisions_log.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "decision": {"ticker": "IWM", "action": "BUY", "signal_mode": "agentic_signal_boost", "metrics": {"rsi": 35}},
                            "outcome": {"pnl_pct": 1.2},
                        }
                    ),
                    json.dumps(
                        {
                            "decision": {"ticker": "QQQ", "action": "BUY", "signal_mode": "deterministic_only", "metrics": {"rsi": 41}},
                            "outcome": {"pnl_pct": -0.7},
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (data_dir / "risk_guardian_state.json").write_text(
            json.dumps({"consecutive_losses": 0, "circuit_breaker_active": False, "position_size_reduction": 1.0}),
            encoding="utf-8",
        )

    def test_run_recursive_evolution_outputs_all_phases(self):
        from agents import recursive_evolution as revo

        with TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / "data"
            logs_dir = root / "logs"
            data_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)
            self._seed_min_artifacts(data_dir)

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                os.environ["FORTRESS_EVOLUTION_ALLOW_WRITES"] = "0"
                out = revo.run_recursive_evolution(data_dir=data_dir)
            finally:
                os.chdir(old_cwd)
                os.environ.pop("FORTRESS_EVOLUTION_ALLOW_WRITES", None)

            self.assertIn("phase1_self_diagnosis", out)
            self.assertIn("phase2_parameter_tuning", out)
            self.assertIn("phase3_strategy_ab_testing", out)
            self.assertIn("phase4_autonomous_changes", out)
            self.assertIn("phase5_meta_learning", out)
            self.assertFalse(out["phase4_autonomous_changes"]["applied"])

    def test_run_recursive_evolution_can_apply_param_patch_when_enabled(self):
        from agents import recursive_evolution as revo

        with TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / "data"
            logs_dir = root / "logs"
            data_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)
            self._seed_min_artifacts(data_dir)
            (data_dir / "current_params.json").write_text(
                json.dumps({"rsi_threshold": 40, "drop_min": -15, "drop_max": -5, "volume_ratio_min": 1.5}),
                encoding="utf-8",
            )
            # Bias to a low win-rate so phase2 proposes stricter params.
            (data_dir / "decisions_log.jsonl").write_text(
                json.dumps(
                    {
                        "decision": {"ticker": "QQQ", "action": "BUY", "signal_mode": "deterministic_only"},
                        "outcome": {"pnl_pct": -1.1},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                # Writes apply only when approval is off; default REQUIRE_APPROVAL=1 queues changes.
                os.environ["FORTRESS_EVOLUTION_ALLOW_WRITES"] = "1"
                os.environ["FORTRESS_EVOLUTION_REQUIRE_APPROVAL"] = "0"
                out = revo.run_recursive_evolution(data_dir=data_dir)
            finally:
                os.chdir(old_cwd)
                os.environ.pop("FORTRESS_EVOLUTION_ALLOW_WRITES", None)
                os.environ.pop("FORTRESS_EVOLUTION_REQUIRE_APPROVAL", None)

            self.assertTrue(out["phase4_autonomous_changes"]["applied"])
            self.assertTrue((data_dir / "current_params.json").exists())
            saved = json.loads((data_dir / "current_params.json").read_text(encoding="utf-8"))
            self.assertEqual(saved.get("updated_by"), "recursive_evolution")


if __name__ == "__main__":
    unittest.main()

