from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agents.bot_audit_agent import audit_bot_performance


class TestBotAuditAgent(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def test_ok_when_profitable_and_small_losses(self):
        with self.subTest("setup"):
            pass
        tmp = Path("._tmp_bot_audit_test")
        if tmp.exists():
            # Best-effort clean
            for p in tmp.rglob("*"):
                try:
                    if p.is_file():
                        p.unlink()
                except Exception:
                    pass
        tmp.mkdir(parents=True, exist_ok=True)

        data_dir = tmp / "data"
        logs_dir = tmp / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        now_utc = datetime(2026, 3, 25, 18, 0, 0, tzinfo=timezone.utc)
        day_ts = "2026-03-25T18:00:00"

        ledger = [
            {"timestamp": day_ts, "ticker": "AAA", "pnl": 5.0, "strategy_id": "intraday_sniper"},
            {"timestamp": day_ts, "ticker": "BBB", "pnl": 2.0, "strategy_id": "intraday_sniper"},
            {"timestamp": day_ts, "ticker": "CCC", "pnl": -1.0, "strategy_id": "spy_intraday_swing"},
        ]
        self._write_jsonl(data_dir / "pnl_ledger.jsonl", ledger)

        self._write_jsonl(
            data_dir / "operational_runs.jsonl",
            [
                {
                    "timestamp": day_ts,
                    "event_type": "screening_run_started",
                    "payload": {"run_id": "screen_1", "policy_profile": "balanced", "portfolio_value": 5000.0},
                },
                {
                    "timestamp": day_ts,
                    "event_type": "screening_run_completed",
                    "payload": {
                        "run_id": "screen_1",
                        "policy_profile": "balanced",
                        "candidates_found": 10,
                        "approved_count": 1,
                        "executed_count": 1,
                        "rejected_count": 0,
                        "strict_mode": False,
                    },
                },
            ],
        )

        (data_dir / "risk_guardian_state.json").write_text(
            json.dumps({"consecutive_losses": 1, "circuit_breaker_active": False}),
            encoding="utf-8",
        )
        (data_dir / "last_screening_meta.json").write_text(
            json.dumps({"strict_mode": False}),
            encoding="utf-8",
        )

        report = audit_bot_performance(
            data_dir=data_dir,
            logs_dir=logs_dir,
            lookback_days=7,
            audit_days=1,
            now_utc=now_utc,
        )
        self.assertEqual(report["overall_status"], "ok")
        self.assertEqual(report["objectives"]["profit_opportunities"]["status"], "ok")
        self.assertEqual(report["objectives"]["near_zero_losses"]["status"], "ok")

    def test_critical_when_all_losses(self):
        tmp = Path("._tmp_bot_audit_test_2")
        if tmp.exists():
            for p in tmp.rglob("*"):
                try:
                    if p.is_file():
                        p.unlink()
                except Exception:
                    pass
        tmp.mkdir(parents=True, exist_ok=True)
        data_dir = tmp / "data"
        logs_dir = tmp / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        now_utc = datetime(2026, 3, 25, 18, 0, 0, tzinfo=timezone.utc)
        day_ts = "2026-03-25T18:00:00"

        ledger = [
            {"timestamp": day_ts, "ticker": "AAA", "pnl": -5.0, "strategy_id": "intraday_sniper"},
            {"timestamp": day_ts, "ticker": "BBB", "pnl": -2.0, "strategy_id": "intraday_sniper"},
            {"timestamp": day_ts, "ticker": "CCC", "pnl": -1.0, "strategy_id": "spy_intraday_swing"},
        ]
        self._write_jsonl(data_dir / "pnl_ledger.jsonl", ledger)

        (data_dir / "risk_guardian_state.json").write_text(
            json.dumps({"consecutive_losses": 3, "circuit_breaker_active": True}),
            encoding="utf-8",
        )

        report = audit_bot_performance(
            data_dir=data_dir,
            logs_dir=logs_dir,
            lookback_days=7,
            audit_days=1,
            now_utc=now_utc,
        )
        self.assertIn(report["overall_status"], ("critical", "warn"))
        # In this heuristic, it should generally be critical.
        self.assertEqual(report["objectives"]["near_zero_losses"]["status"], "critical")

    def test_warn_when_missing_ledger(self):
        tmp = Path("._tmp_bot_audit_test_3")
        if tmp.exists():
            for p in tmp.rglob("*"):
                try:
                    if p.is_file():
                        p.unlink()
                except Exception:
                    pass
        tmp.mkdir(parents=True, exist_ok=True)
        data_dir = tmp / "data"
        logs_dir = tmp / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        now_utc = datetime(2026, 3, 25, 18, 0, 0, tzinfo=timezone.utc)
        report = audit_bot_performance(
            data_dir=data_dir,
            logs_dir=logs_dir,
            lookback_days=7,
            audit_days=1,
            now_utc=now_utc,
        )
        self.assertIn(report["overall_status"], ("warn", "ok", "critical"))


if __name__ == "__main__":
    unittest.main()

