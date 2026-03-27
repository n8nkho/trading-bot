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
LOG_PATH = DATA_DIR / "geographic_execution_log.jsonl"


def _is_first_monday_window(today_et: date) -> bool:
    return today_et.weekday() == 0 and 1 <= today_et.day <= 7


def _latest_geo_plan(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    files = sorted(data_dir.glob("geographic_allocation_plan_*.json"), reverse=True)
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


def run_geographic_allocation_execution(*, force: bool = False) -> dict[str, Any]:
    now_et = datetime.now(ET)
    today = now_et.date()
    plan = _latest_geo_plan(DATA_DIR)
    if not plan:
        return {"ok": False, "reason": "missing_geographic_plan"}
    if not force and not _is_first_monday_window(today):
        return {"ok": True, "skipped": True, "reason": "not_first_monday_window"}

    rows = plan.get("allocations") if isinstance(plan.get("allocations"), list) else []
    if not rows:
        return {"ok": False, "reason": "no_allocations"}

    client = _build_client()
    if client is None:
        return {"ok": False, "reason": "alpaca_client_unavailable"}

    broker_positions, _err = fetch_broker_positions()
    by_symbol = {str((p or {}).get("ticker") or "").upper(): p for p in (broker_positions or [])}
    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in rows:
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        target_usd = float(row.get("target_usd") or 1600.0)
        if sym in by_symbol:
            skipped.append({"symbol": sym, "reason": "already_held"})
            continue

        import yfinance as yf

        hist = yf.Ticker(sym).history(period="1d")
        if hist.empty:
            skipped.append({"symbol": sym, "reason": "price_unavailable"})
            continue
        px = float(hist["Close"].iloc[-1])
        qty = int(target_usd / px)
        if qty < 1:
            skipped.append({"symbol": sym, "reason": "qty_below_1"})
            continue

        gate = evaluate_pre_trade_submission(
            side="BUY",
            symbol=sym,
            qty=float(qty),
            estimated_notional_usd=qty * px,
        )
        if not gate.get("allowed"):
            skipped.append({"symbol": sym, "reason": format_gate_block_message(gate)})
            continue

        req = MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        try:
            order = client.submit_order(req)
            executed.append(
                {
                    "symbol": sym,
                    "qty": qty,
                    "target_usd": round(target_usd, 2),
                    "hedge_symbol": row.get("hedge_symbol"),
                    "order_id": str(order.id),
                }
            )
        except Exception as e:
            skipped.append({"symbol": sym, "reason": f"submit_failed:{type(e).__name__}"})

    out = {
        "timestamp": now_et.isoformat(),
        "ok": True,
        "international_capital_usd": float(plan.get("international_capital_usd") or 4000.0),
        "executed_count": len(executed),
        "skipped_count": len(skipped),
        "executed": executed,
        "skipped": skipped,
        "hedge_rule": plan.get("hedge_rule"),
    }
    _append_log(out)
    return out

