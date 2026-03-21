"""
Smoke test: ensure orchestrator only persists positions after FILLED orders.
"""

import json
import time
from datetime import datetime


def main():
    import os
    # Avoid import-time Alpaca client initialization crashes (credentials required by alpaca-py).
    os.environ.setdefault("APCA_API_KEY_ID", "smoke_dummy_key")
    os.environ.setdefault("APCA_API_SECRET_KEY", "smoke_dummy_secret")
    import orchestrator as orch

    portfolio_value = 10000.0

    # Use configured watchlist ticker (no hard-coded tickers in this smoke script).
    with open("config/watchlist.json", "r") as f:
        quality_stocks = json.load(f).get("quality_stocks") or []
    if not quality_stocks:
        raise SystemExit("No tickers found in config/watchlist.json (quality_stocks empty).")
    ticker = str(quality_stocks[0].get("ticker")).strip().upper()

    # Deterministic single candidate.
    mock_candidates = [
        {
            "ticker": ticker,
            "sector": "Technology",
            "current_price": 100.0,
            "drop_pct": -10.0,
            "rsi": 25.0,
            "volume_ratio": 2.0,
            "news": ["mock headline"],
            "vision_signal": None,
            "analysis": {"confidence": 0.9},
        }
    ]

    orch.run_screener = lambda: mock_candidates
    orch.check_risk_limits = lambda portfolio_data, new_position, strict_mode=False: {
        "approved": True,
        "reason": "mock ok",
    }

    # Force a stock BUY decision.
    orch.evaluate_entry = lambda candidates, portfolio_value: [
        {
            "ticker": ticker,
            "action": "BUY",
            "reason": "mock entry",
            "reasoning": "mock entry",
            "position_size": 100.0,
            "shares": 1,
            "entry_price": 100.0,
            "confidence": 0.9,
            "timestamp": datetime.now().isoformat(),
            "trade_type": "STOCK",
        }
    ]

    orch.get_account_info = lambda: {
        "buying_power": 1e9,
        "equity": portfolio_value,
        "cash": 1e9,
        "portfolio_value": portfolio_value,
        "position_count": 0,
    }
    orch.load_positions = lambda: []
    orch.load_current_params = lambda: {"rsi_threshold": 40, "stop_loss_pct": -2.0, "take_profit_pct": 15.0}

    persisted_positions = []
    orch.add_position = lambda pos: persisted_positions.append(pos)

    # Fake order: ACCEPTED but not FILLED, no filled price.
    orch.execute_buy_order = lambda ticker, shares, entry_price: {
        "success": True,
        "order_id": "mock_order_accepted",
        "filled_qty": None,
        "filled_price": None,
        "status": "accepted",
        "error": None,
    }

    result = orch.run_daily_screening(portfolio_value=portfolio_value)
    assert result["candidates_found"] == 1
    assert result["approved_trades"] and len(result["approved_trades"]) == 1
    assert len(result.get("executed_trades", [])) == 0, "Order should not be treated as executed when not FILLED"
    assert len(persisted_positions) == 0, "Position should not be persisted for non-filled orders"

    print("[smoke] smoke_order_filled_gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

