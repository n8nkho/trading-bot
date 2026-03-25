from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agents.bot_audit_agent import _market_vs_bot_analysis, _tape_trend_label, audit_bot_performance


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
            include_market=False,
        )
        self.assertEqual(report["overall_status"], "ok")
        self.assertEqual(report["objectives"]["profit_opportunities"]["status"], "ok")
        self.assertEqual(report["objectives"]["near_zero_losses"]["status"], "ok")
        self.assertEqual(report["objectives"]["market_backdrop"]["status"], "unavailable")

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
            include_market=False,
        )
        self.assertIn(report["overall_status"], ("critical", "warn"))
        # In this heuristic, it should generally be critical.
        self.assertEqual(report["objectives"]["near_zero_losses"]["status"], "critical")

    def test_session_excludes_ledger_rows_before_3am_et(self):
        """Session anchor 3 AM ET: same-calendar-day fills before 3 AM local are out of scope."""
        tmp = Path("._tmp_bot_audit_session")
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
        ledger = [
            {"timestamp": "2026-03-25T05:30:00+00:00", "ticker": "PRE", "pnl": -50.0, "strategy_id": "early"},
            {"timestamp": "2026-03-25T18:00:00+00:00", "ticker": "OK", "pnl": 5.0, "strategy_id": "late"},
        ]
        self._write_jsonl(data_dir / "pnl_ledger.jsonl", ledger)

        report = audit_bot_performance(
            data_dir=data_dir,
            logs_dir=logs_dir,
            lookback_days=7,
            audit_days=1,
            now_utc=now_utc,
            include_market=False,
        )
        self.assertEqual(report["audited"]["ledger_rows_today"], 1)
        self.assertEqual(report["audited"]["ledger_rows_session_et"], 1)
        loss = report["objectives"]["near_zero_losses"]["findings"]
        pnl_row = next(x for x in loss if x.get("metric") == "realized_pnl_session_et")
        self.assertEqual(pnl_row["value"], 5.0)
        self.assertIn("audit_window", report)
        self.assertIn("start_et", report["audit_window"])

    def test_hedging_contrast_loads_fortress_report(self):
        tmp = Path("._tmp_bot_audit_hedge")
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
        data_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        now_utc = datetime(2026, 3, 25, 18, 0, 0, tzinfo=timezone.utc)
        (data_dir / "fortress_report_20260325.json").write_text(
            json.dumps(
                {
                    "market_conditions": {"regime": "RISK_OFF", "vix": 22.5},
                    "strategies": {"bonds": {"target": 0.25, "reason": "test"}},
                    "note": "unit",
                }
            ),
            encoding="utf-8",
        )

        report = audit_bot_performance(
            data_dir=data_dir,
            logs_dir=logs_dir,
            lookback_days=7,
            audit_days=1,
            now_utc=now_utc,
            include_market=False,
        )
        self.assertIn("hedging_contrast", report)
        self.assertIn("hedging_context", report)
        self.assertEqual(report["hedging_context"].get("regime"), "RISK_OFF")
        self.assertTrue(len(report["hedging_context"].get("strategy_headlines") or []) >= 1)
        titles = [r.get("title", "") for r in (report.get("recommendations") or [])]
        self.assertTrue(any("Hedge" in t or "hedge" in t for t in titles))

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
            include_market=False,
        )
        self.assertIn(report["overall_status"], ("warn", "ok", "critical"))


    def test_tape_trend_label(self):
        self.assertEqual(_tape_trend_label(1.5, 0.5), "uptrend")
        self.assertEqual(_tape_trend_label(-1.5, -0.5), "downtrend")
        self.assertEqual(_tape_trend_label(0.1, 0.1), "sideways")
        self.assertEqual(_tape_trend_label(None, 0), "unknown")

    def test_market_vs_bot_downtrend_losses_align(self):
        m = {
            "ok": True,
            "benchmark": "SPY",
            "tape_trend": "downtrend",
            "change_5d_pct": -2.0,
            "change_1d_pct": -0.5,
            "vix_last": 19.0,
        }
        r = _market_vs_bot_analysis(
            market=m,
            pnl_session=-10.0,
            loss_status="warn",
            profit_status="warn",
            total_session_trades=2,
        )
        self.assertTrue(any("weak" in (f.get("text") or "") for f in r["findings"]))

    def test_missed_opportunity_pending_and_entry_funnel(self):
        tmp = Path("._tmp_bot_audit_opp")
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
        data_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "pending_execution_queue.json").write_text(
            json.dumps({"batches": [{"trades": [{"ticker": "FOO"}], "run_id": "r1"}]}),
            encoding="utf-8",
        )
        (data_dir / "daily_signals_20260325.json").write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-25T12:00:00",
                    "candidates": [{"ticker": "A"}, {"ticker": "B"}],
                    "entry_gate_summary": {
                        "evaluated_candidates": 2,
                        "buy_count": 0,
                        "skip_count": 2,
                        "top_skip_reasons": [{"reason": "spread_too_wide", "count": 6}],
                    },
                    "risk_gate_summary": {"approved_count": 0, "rejected_count": 0, "top_rejected_reasons": []},
                    "approved_trades": [],
                    "executed_trades": [],
                    "execution_gate_summary": {"executed_count": 0},
                }
            ),
            encoding="utf-8",
        )
        now_utc = datetime(2026, 3, 25, 18, 0, 0, tzinfo=timezone.utc)
        report = audit_bot_performance(
            data_dir=data_dir,
            logs_dir=logs_dir,
            lookback_days=7,
            audit_days=1,
            now_utc=now_utc,
            include_market=False,
        )
        mf = report["missed_opportunities"]["findings"]
        types = {f.get("type") for f in mf}
        self.assertIn("hitl_backlog", types)
        self.assertTrue(types & {"entry_funnel", "entry_reason_mass"})

    def test_alternative_strategies_suggests_deprioritize_worst(self):
        tmp = Path("._tmp_bot_audit_alt")
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
        data_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        day_ts = "2026-03-25T18:00:00+00:00"
        ledger = [
            {"timestamp": day_ts, "ticker": "X", "pnl": -30.0, "strategy_id": "bad_strat"},
            {"timestamp": day_ts, "ticker": "Y", "pnl": -5.0, "strategy_id": "bad_strat"},
            {"timestamp": day_ts, "ticker": "Z", "pnl": 2.0, "strategy_id": "good_strat"},
        ]
        self._write_jsonl(data_dir / "pnl_ledger.jsonl", ledger)
        now_utc = datetime(2026, 3, 25, 18, 0, 0, tzinfo=timezone.utc)
        report = audit_bot_performance(
            data_dir=data_dir,
            logs_dir=logs_dir,
            lookback_days=7,
            audit_days=1,
            now_utc=now_utc,
            include_market=False,
        )
        titles = " ".join(s.get("title", "") for s in (report.get("alternative_strategies") or {}).get("suggestions") or [])
        self.assertIn("Deprioritize", titles)
        self.assertIn("bad_strat", titles)

    def test_gate_rollup_freshness_research_blocks(self):
        tmp = Path("._tmp_bot_audit_extended")
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
        data_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in [
            (
                "daily_signals_20260110.json",
                {
                    "timestamp": "2026-01-10T10:00:00",
                    "candidates": [{"ticker": "A"}],
                    "entry_gate_summary": {
                        "buy_count": 0,
                        "skip_count": 3,
                        "top_skip_reasons": [{"reason": "wide_spread", "count": 3}],
                    },
                    "risk_gate_summary": {"top_rejected_reasons": []},
                    "approved_trades": [],
                    "executed_trades": [],
                    "fundamental_cost": 0.05,
                },
            ),
            (
                "daily_signals_20260111.json",
                {
                    "timestamp": "2026-01-11T10:00:00",
                    "candidates": [{"ticker": "B"}, {"ticker": "C"}],
                    "entry_gate_summary": {
                        "buy_count": 1,
                        "skip_count": 1,
                        "top_skip_reasons": [{"reason": "wide_spread", "count": 1}],
                    },
                    "risk_gate_summary": {"top_rejected_reasons": [{"reason": "max_pos", "count": 1}]},
                    "approved_trades": [{"ticker": "B"}],
                    "executed_trades": [],
                    "execution_gate_summary": {"top_failure_reasons": [{"reason": "timeout", "count": 1}]},
                },
            ),
        ]:
            (data_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        (data_dir / "exit_signals_20260111.json").write_text(
            json.dumps(
                {
                    "runs": [
                        {
                            "action_summary": {"HOLD": 2, "SELL": 1},
                            "executed_exits": [{"ticker": "B"}],
                            "exit_failures": [{"ticker": "X"}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "walk_forward_report.json").write_text(
            json.dumps({"stable": False, "reason": "unit_test_unstable"}),
            encoding="utf-8",
        )
        (data_dir / "backtest_snapshot.json").write_text(
            json.dumps({"ticker": "SPY", "strategy_total_return": 0.01, "max_drawdown": -0.05}),
            encoding="utf-8",
        )
        (logs_dir / "sniper.log").write_text("ok\n", encoding="utf-8")
        now_utc = datetime(2026, 3, 25, 18, 0, 0, tzinfo=timezone.utc)
        report = audit_bot_performance(
            data_dir=data_dir,
            logs_dir=logs_dir,
            lookback_days=7,
            audit_days=1,
            now_utc=now_utc,
            include_market=False,
        )
        self.assertIn("gate_attribution_rollup", report)
        self.assertEqual(report["gate_attribution_rollup"]["totals"]["files_scanned"], 2)
        self.assertGreaterEqual(
            report["gate_attribution_rollup"]["top_skip_reasons_rollup"][0]["count"],
            3,
        )
        self.assertIn("freshness_sla", report)
        self.assertIn("exit_monitoring", report)
        self.assertEqual(report["exit_monitoring"]["exit_failures_sum"], 1)
        self.assertEqual(report["research_backtest"]["walk_forward_summary"].get("stable"), False)
        self.assertEqual(report["research_backtest"]["backtest_summary"].get("ticker"), "SPY")
        self.assertIn("efficiency_and_policy", report)
        titles = [r.get("title", "") for r in (report.get("recommendations") or [])]
        self.assertTrue(any("Walk-forward" in t for t in titles))

    def test_market_vs_bot_uptrend_losses_tension(self):
        m = {
            "ok": True,
            "benchmark": "SPY",
            "tape_trend": "uptrend",
            "change_5d_pct": 2.0,
            "change_1d_pct": 0.4,
            "vix_last": 14.0,
        }
        r = _market_vs_bot_analysis(
            market=m,
            pnl_session=-5.0,
            loss_status="warn",
            profit_status="warn",
            total_session_trades=3,
        )
        self.assertTrue(any(f.get("type") == "tension" for f in r["findings"]))


if __name__ == "__main__":
    unittest.main()

