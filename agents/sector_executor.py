from __future__ import annotations

import json
import os
from datetime import datetime, date
from pathlib import Path
from typing import Any

import pytz
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from utils.alpaca_broker import fetch_broker_positions
from utils.pre_trade_gate import evaluate_pre_trade_submission, format_gate_block_message


ET = pytz.timezone("US/Eastern")
DATA_DIR = Path("data")
LOG_PATH = DATA_DIR / "sector_execution_log.jsonl"


def _is_first_trading_day_of_month(today_et: date) -> bool:
    d = date(today_et.year, today_et.month, 1)
    while d.weekday() >= 5:  # weekend -> next Monday
        d = date.fromordinal(d.toordinal() + 1)
    return today_et == d


def _latest_sector_signal(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    files = sorted(data_dir.glob("sector_rotation_signal_*.json"), reverse=True)
    if not files:
        return {}
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return {}


def _append_log(row: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _build_client() -> TradingClient | None:
    key = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        return None
    return TradingClient(key, secret, paper=True)


def run_sector_rotation_execution(*, force: bool = False) -> dict[str, Any]:
    now_et = datetime.now(ET)
    today = now_et.date()
    signal = _latest_sector_signal(DATA_DIR)
    if not signal:
        return {"ok": False, "reason": "missing_sector_rotation_signal"}
    if not force and not _is_first_trading_day_of_month(today):
        return {"ok": True, "skipped": True, "reason": "not_first_trading_day"}

    sleeve_capital = float(signal.get("sleeve_capital_usd") or 6000.0)
    picks = signal.get("signals") if isinstance(signal.get("signals"), list) else []
    if not picks:
        return {"ok": False, "reason": "no_sector_signals"}

    client = _build_client()
    if client is None:
        return {"ok": False, "reason": "alpaca_client_unavailable"}

    broker_positions, _err = fetch_broker_positions()
    by_symbol = {str((p or {}).get("ticker") or "").upper(): p for p in (broker_positions or [])}
    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in picks:
        sym = str(row.get("sector") or "").strip().upper()
        if not sym:
            continue
        w = float(row.get("weight_pct") or 0.0)
        target_usd = sleeve_capital * (w / 100.0)
        if target_usd <= 0:
            skipped.append({"symbol": sym, "reason": "non_positive_target_usd"})
            continue
        if sym in by_symbol:
            skipped.append({"symbol": sym, "reason": "already_held"})
            continue
        try:
            last_price = float(by_symbol.get(sym, {}).get("price") or 0.0)
        except Exception:
            last_price = 0.0
        if last_price <= 0:
            # Price from yfinance fallback.
            import yfinance as yf

            hist = yf.Ticker(sym).history(period="1d")
            if hist.empty:
                skipped.append({"symbol": sym, "reason": "price_unavailable"})
                continue
            last_price = float(hist["Close"].iloc[-1])
        qty = int(target_usd / last_price)
        if qty < 1:
            skipped.append({"symbol": sym, "reason": "qty_below_1"})
            continue

        gate = evaluate_pre_trade_submission(
            side="BUY",
            symbol=sym,
            qty=float(qty),
            estimated_notional_usd=qty * last_price,
        )
        if not gate.get("allowed"):
            skipped.append({"symbol": sym, "reason": format_gate_block_message(gate)})
            continue

        req = MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        try:
            order = client.submit_order(req)
            executed.append({"symbol": sym, "qty": qty, "target_usd": round(target_usd, 2), "order_id": str(order.id)})
        except Exception as e:
            skipped.append({"symbol": sym, "reason": f"submit_failed:{type(e).__name__}"})

    out = {
        "timestamp": now_et.isoformat(),
        "ok": True,
        "sleeve_capital_usd": sleeve_capital,
        "executed_count": len(executed),
        "skipped_count": len(skipped),
        "executed": executed,
        "skipped": skipped,
    }
    _append_log(out)
    return out

