#!/usr/bin/env python3
"""
Sync Alpaca paper-trading positions to data/positions.json

This script is used by cron and Command Center to keep the local
positions file in sync with Alpaca. It is conservative:
- Reads ALPACA_API_KEY / ALPACA_SECRET_KEY from env or .env
- Writes to project-root data/positions.json
- Preserves existing entry_time when possible
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from alpaca.trading.client import TradingClient


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
POSITIONS_FILE = DATA_DIR / "positions.json"
ENV_FILE = ROOT / ".env"


def _load_env_from_file() -> None:
    if not ENV_FILE.exists():
        return
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key in {"ALPACA_API_KEY", "ALPACA_SECRET_KEY"} and not os.getenv(key):
                os.environ[key] = val
    except Exception:
        # Best-effort; orchestrator will surface credential issues separately
        pass


def _load_existing_entry_times() -> dict[str, str]:
    entry_times: dict[str, str] = {}
    try:
        if POSITIONS_FILE.exists():
            with open(POSITIONS_FILE) as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                existing = existing.get("positions", existing.get("positions_list", []))
            for p in existing or []:
                if not isinstance(p, dict):
                    continue
                ticker = p.get("ticker")
                et = p.get("entry_time") or p.get("entry_date")
                if ticker and et:
                    entry_times[str(ticker)] = str(et)
    except Exception:
        pass
    return entry_times


def main() -> int:
    _load_env_from_file()
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not api_secret:
        print("ALPACA_API_KEY / ALPACA_SECRET_KEY not set; skipping sync.")
        return 1

    try:
        client = TradingClient(api_key, api_secret, paper=True)
    except ValueError as e:
        print(f"Alpaca auth invalid: {e}. Check API keys in .env.")
        return 1

    existing_entry_times = _load_existing_entry_times()

    positions = client.get_all_positions()
    pos_list: list[dict] = []

    now_iso = datetime.now().isoformat()
    for pos in positions:
        ticker = str(pos.symbol)
        entry_time = existing_entry_times.get(ticker, now_iso)
        qty = float(pos.qty)
        entry_price = float(pos.avg_entry_price)
        current_price = float(pos.current_price)
        unrealized_pl = float(pos.unrealized_pl)
        cost_basis = float(pos.cost_basis)
        pnl_pct = (unrealized_pl / cost_basis) * 100 if cost_basis else 0.0

        pos_list.append(
            {
                "ticker": ticker,
                "qty": qty,
                "entry_price": entry_price,
                "current_price": current_price,
                "pnl": unrealized_pl,
                "pnl_pct": pnl_pct,
                "entry_time": entry_time,
                "cost_basis": cost_basis,
            }
        )

    DATA_DIR.mkdir(exist_ok=True)
    with open(POSITIONS_FILE, "w") as f:
        json.dump(pos_list, f, indent=2)

    print(f"✅ Synced {len(pos_list)} positions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

