"""Drift alert and rollback require recent realized trading activity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


def test_has_recent_trading_activity_false_when_ledger_empty(tmp_path) -> None:
    from utils.trading_activity import has_recent_trading_activity

    ledger = tmp_path / "pnl_ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    assert has_recent_trading_activity(10, ledger_path=ledger) is False


def test_has_recent_trading_activity_true_for_recent_fill(tmp_path) -> None:
    from utils.trading_activity import has_recent_trading_activity

    ledger = tmp_path / "pnl_ledger.jsonl"
    ts = datetime.now(timezone.utc).isoformat()
    ledger.write_text(f'{{"pnl": 1.0, "timestamp": "{ts}"}}\n', encoding="utf-8")
    assert has_recent_trading_activity(10, ledger_path=ledger) is True


def test_analyze_drift_suppresses_alert_without_recent_activity(tmp_path, monkeypatch) -> None:
    import agents.drift_detector as dd

    ledger = tmp_path / "data" / "pnl_ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    old = datetime.now(timezone.utc) - timedelta(days=30)
    ledger.write_text(f'{{"pnl": 5.0, "timestamp": "{old.isoformat()}"}}\n' * 50, encoding="utf-8")
    out_path = tmp_path / "data" / "drift_report.json"

    monkeypatch.setattr(dd, "LEDGER", ledger)
    monkeypatch.setattr(dd, "OUT", out_path)

    with (
        patch("utils.trading_activity.has_recent_trading_activity", return_value=False),
        patch("utils.policy_guardrails.maybe_clear_forced_rollback_on_recovery", return_value=None),
        patch("utils.policy_guardrails.maybe_trigger_rollback_on_drift") as trig,
    ):
        report = dd.analyze_drift()

    assert report["drift_alert"] is False
    assert report["reason"] == "no_recent_trading_activity"
    trig.assert_called_once()


def test_maybe_trigger_rollback_skips_without_recent_activity() -> None:
    from utils import policy_guardrails as pg

    guard = {
        "auto_rollback_on_drift_alert": True,
        "rollback_target_profile": "capital_preservation",
        "rollback_duration_hours": 168,
    }
    drift = {
        "drift_alert": True,
        "recent_avg_pnl": 1.0,
        "prior_avg_pnl": 10.0,
        "drift_ratio": -0.9,
        "reason": "recent_performance_deterioration",
    }
    with (
        patch.object(pg, "get_guardrails", return_value=guard),
        patch("utils.trading_activity.has_recent_trading_activity", return_value=False),
        patch.object(pg, "_save_rollback_state") as save,
    ):
        out = pg.maybe_trigger_rollback_on_drift(drift)
    assert out is None
    save.assert_not_called()
