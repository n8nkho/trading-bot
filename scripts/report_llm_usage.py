#!/usr/bin/env python3
"""
Report LLM token usage and estimated costs.

Reads data/api_costs.jsonl and prints:
- last 20 calls
- today's usage/cost
- 7-day summary
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


DATA = Path("data")
API_COSTS = DATA / "api_costs.jsonl"


def _load_rows() -> list[dict]:
    rows: list[dict] = []
    if not API_COSTS.exists():
        return rows
    with open(API_COSTS, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def main() -> int:
    rows = _load_rows()
    if not rows:
        print("No API usage records yet (data/api_costs.jsonl is empty/missing).")
        return 0

    print("=== Last 20 LLM API calls ===")
    for r in rows[-20:]:
        print(
            f"{r.get('timestamp')} | {r.get('service')}/{r.get('model')} | "
            f"in={r.get('input_tokens', 0)} out={r.get('output_tokens', 0)} | "
            f"cost=${float(r.get('cost_with_cache', 0.0)):.6f}"
        )

    today = datetime.now().date()
    daily = [r for r in rows if datetime.fromisoformat(str(r.get("timestamp"))).date() == today]
    in_t = sum(int(r.get("input_tokens", 0) or 0) for r in daily)
    out_t = sum(int(r.get("output_tokens", 0) or 0) for r in daily)
    cost = sum(float(r.get("cost_with_cache", 0.0) or 0.0) for r in daily)
    print("\n=== Today ===")
    print(f"calls={len(daily)} input_tokens={in_t} output_tokens={out_t} est_cost=${cost:.4f}")

    print("\n=== Last 7 days summary ===")
    by_day: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cost": 0.0})
    cutoff = today - timedelta(days=6)
    for r in rows:
        d = datetime.fromisoformat(str(r.get("timestamp"))).date()
        if d < cutoff:
            continue
        key = d.isoformat()
        by_day[key]["calls"] += 1
        by_day[key]["in"] += int(r.get("input_tokens", 0) or 0)
        by_day[key]["out"] += int(r.get("output_tokens", 0) or 0)
        by_day[key]["cost"] += float(r.get("cost_with_cache", 0.0) or 0.0)
    for key in sorted(by_day.keys()):
        d = by_day[key]
        print(f"{key}: calls={int(d['calls'])} in={int(d['in'])} out={int(d['out'])} cost=${d['cost']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

