"""Drift rollback idempotency: avoid trust-ledger spam on repeated analyze_drift calls."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


@pytest.fixture
def drift_report() -> dict:
    return {
        "drift_alert": True,
        "recent_avg_pnl": -1.0,
        "prior_avg_pnl": 1.0,
        "drift_ratio": 2.0,
    }


def test_maybe_trigger_rollback_skips_when_same_drift_rollback_active(
    drift_report: dict,
) -> None:
    from utils import policy_guardrails as pg

    future = (datetime.now() + timedelta(hours=1)).isoformat()
    existing = {
        "forced_profile": "capital_preservation",
        "forced_reason": "drift_alert",
        "forced_until": future,
    }
    guard = {
        "auto_rollback_on_drift_alert": True,
        "rollback_target_profile": "capital_preservation",
        "rollback_duration_hours": 168,
    }
    with (
        patch.object(pg, "get_guardrails", return_value=guard),
        patch.object(pg, "_load_rollback_state", return_value=existing),
        patch.object(pg, "_save_rollback_state") as save,
        patch("utils.trust_ledger.append_trust_event") as append,
    ):
        out = pg.maybe_trigger_rollback_on_drift(drift_report)
    assert out is None
    save.assert_not_called()
    append.assert_not_called()


def test_maybe_trigger_rollback_reapplies_when_expired(drift_report: dict) -> None:
    from utils import policy_guardrails as pg

    past = (datetime.now() - timedelta(hours=1)).isoformat()
    existing = {
        "forced_profile": "capital_preservation",
        "forced_reason": "drift_alert",
        "forced_until": past,
    }
    guard = {
        "auto_rollback_on_drift_alert": True,
        "rollback_target_profile": "capital_preservation",
        "rollback_duration_hours": 168,
    }
    with (
        patch.object(pg, "get_guardrails", return_value=guard),
        patch.object(pg, "_load_rollback_state", return_value=existing),
        patch.object(pg, "_save_rollback_state") as save,
        patch("utils.trust_ledger.append_trust_event") as append,
        patch("utils.trading_activity.has_recent_trading_activity", return_value=True),
    ):
        out = pg.maybe_trigger_rollback_on_drift(drift_report)
    assert out is not None
    assert out.get("action") == "rollback_applied"
    save.assert_called_once()
    append.assert_called_once()
