#!/usr/bin/env python3
"""
Sync Alpaca broker open positions -> data/positions.json.

Uses ALPACA_API_KEY / ALPACA_SECRET_KEY and ALPACA_BASE_URL:
- URL contains "paper" -> paper trading client (default).
- Live URL (e.g. api.alpaca.markets) -> live client (only if your .env matches live keys).

Run from repo root:
  python3 sync_alpaca.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except Exception:
    pass

from utils.alpaca_broker import fetch_broker_positions
from utils.alpaca_env import is_alpaca_paper

# When re-syncing from broker, preserve bot-managed fields so tier / signal tracking survives.
_MERGE_KEYS = (
    "tiers_sold",
    "signal_id",
    "entry_time",
    "entry_date",
    "type",
    "sector",
    "notes",
)


def _merge_prior_metadata(
    broker_rows: list[dict], prior_path: Path
) -> list[dict]:
    if not prior_path.exists():
        return broker_rows
    try:
        raw = json.loads(prior_path.read_text(encoding="utf-8"))
    except Exception:
        return broker_rows
    if not isinstance(raw, list):
        return broker_rows
    by_ticker: dict[str, dict] = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        t = str(row.get("ticker") or "").strip().upper()
        if t:
            by_ticker[t] = row
    for p in broker_rows:
        if not isinstance(p, dict):
            continue
        t = str(p.get("ticker") or "").strip().upper()
        old = by_ticker.get(t)
        if not old:
            continue
        for key in _MERGE_KEYS:
            if key in old and old[key] is not None:
                p[key] = old[key]
        ts = p.get("tiers_sold")
        if isinstance(ts, dict):
            for k in ("tier1", "tier2", "tier3", "tier4"):
                ts.setdefault(k, False)
            p["tiers_sold"] = ts
    return broker_rows


def main() -> int:
    positions, err = fetch_broker_positions()
    if err:
        print(f"❌ {err}", file=sys.stderr)
        return 1
    # Orchestrator accepts qty or shares
    for p in positions:
        if "shares" not in p and p.get("qty") is not None:
            p["shares"] = p["qty"]
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "positions.json"
    positions = _merge_prior_metadata(positions, out_path)
    out_path.write_text(json.dumps(positions, indent=2), encoding="utf-8")
    mode = "paper" if is_alpaca_paper() else "live"
    print(f"✅ Synced {len(positions)} positions from Alpaca ({mode}) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
