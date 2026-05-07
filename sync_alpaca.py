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
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(positions, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    mode = "paper" if is_alpaca_paper() else "live"
    print(f"✅ Synced {len(positions)} positions from Alpaca ({mode}) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
