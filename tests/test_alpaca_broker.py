"""Tests for Alpaca position normalization (Command Center / Alpaca parity)."""
from types import SimpleNamespace

from utils.alpaca_broker import normalize_alpaca_position


def test_normalize_uses_unrealized_plpc_ratio():
    pos = SimpleNamespace(
        symbol="AAPL",
        qty="5",
        avg_entry_price="100.0",
        current_price="120.0",
        cost_basis="500.0",
        unrealized_pl="100.0",
        unrealized_plpc="0.20",
    )
    d = normalize_alpaca_position(pos)
    assert d["ticker"] == "AAPL"
    assert d["qty"] == 5.0
    assert d["entry_price"] == 100.0
    assert d["current_price"] == 120.0
    assert d["pnl"] == 100.0
    assert d["pnl_pct"] == 20.0
    assert d["source"] == "alpaca_broker"


def test_normalize_missing_current_price_not_coerced_to_zero():
    pos = SimpleNamespace(
        symbol="XYZ",
        qty="1",
        avg_entry_price="10.0",
        current_price=None,
        cost_basis="10.0",
        unrealized_pl="0.5",
        unrealized_plpc="0.05",
    )
    d = normalize_alpaca_position(pos)
    assert d["current_price"] is None
    assert d["pnl"] == 0.5


def test_normalize_plpc_fallback_when_missing():
    pos = SimpleNamespace(
        symbol="AAPL",
        qty="2",
        avg_entry_price="100",
        current_price="110",
        cost_basis="200",
        unrealized_pl="20",
        unrealized_plpc=None,
    )
    d = normalize_alpaca_position(pos)
    assert d["pnl_pct"] == 10.0
