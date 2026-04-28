from __future__ import annotations

from utils.trade_history import _normalize_pnl_fields


def test_normalize_uses_fraction_to_percent():
    row = _normalize_pnl_fields({"pnl_pct_fraction": 0.025})
    assert row["pnl_pct"] == 2.5


def test_normalize_preserves_existing_percent():
    row = _normalize_pnl_fields({"pnl_pct": -1.75, "pnl_pct_fraction": -0.01})
    assert row["pnl_pct"] == -1.75
