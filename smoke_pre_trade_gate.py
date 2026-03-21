#!/usr/bin/env python3
"""Smoke: pre-trade gate blocks and allows (Phase B)."""
from __future__ import annotations

import os

from utils.pre_trade_gate import evaluate_pre_trade_submission, format_gate_block_message
from utils.operator_halt import set_trading_halt


def main() -> int:
    # Allow baseline
    g0 = evaluate_pre_trade_submission(
        side="BUY", symbol="AAPL", qty=1, estimated_notional_usd=100.0
    )
    assert g0["allowed"], g0

    os.environ["FORTRESS_TRADING_HALT"] = "1"
    g1 = evaluate_pre_trade_submission(
        side="BUY", symbol="AAPL", qty=1, estimated_notional_usd=100.0
    )
    assert not g1["allowed"], g1
    assert "global_trading_halt" in g1["reasons"]
    del os.environ["FORTRESS_TRADING_HALT"]

    set_trading_halt(True, reason="smoke_file_halt", actor="smoke_pre_trade_gate")
    g_file = evaluate_pre_trade_submission(
        side="BUY", symbol="AAPL", qty=1, estimated_notional_usd=100.0
    )
    assert not g_file["allowed"], g_file
    assert "global_trading_halt" in g_file["reasons"]
    set_trading_halt(False, reason="smoke_reset", actor="smoke_pre_trade_gate")

    os.environ["FORTRESS_MAX_ORDER_NOTIONAL_USD"] = "50"
    g2 = evaluate_pre_trade_submission(
        side="BUY", symbol="AAPL", qty=1, estimated_notional_usd=9999.0
    )
    assert not g2["allowed"], g2
    assert any("notional" in x for x in g2["reasons"])
    del os.environ["FORTRESS_MAX_ORDER_NOTIONAL_USD"]

    os.environ["ALPACA_BASE_URL"] = "https://api.alpaca.markets"
    g3 = evaluate_pre_trade_submission(side="BUY", symbol="AAPL", qty=1)
    assert not g3["allowed"], g3
    assert any("live" in x or "paper" in x for x in g3["reasons"])
    os.environ["ALPACA_BASE_URL"] = "https://paper-api.alpaca.markets"

    msg = format_gate_block_message(g1)
    assert "pre_trade_gate" in msg

    print("[OK] smoke_pre_trade_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
