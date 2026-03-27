#!/usr/bin/env python3
"""
Validate that risk guardian configured limits match active policy profile.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POLICY_FILE = ROOT / "config" / "policy_profiles.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from agents.risk_guardian import get_risk_status

    print("Validating risk guardian configuration...\n")
    with open(POLICY_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    active = str(cfg.get("active_profile") or "balanced")
    expected = ((cfg.get("profiles") or {}).get(active) or {}).get("risk") or {}
    status = get_risk_status()

    checks = [
        ("max_positions", status.get("max_positions"), expected.get("max_positions")),
        ("max_position_size_pct", status.get("max_position_size_pct"), expected.get("max_position_size_pct")),
        ("max_total_risk_pct", status.get("max_total_risk_pct"), expected.get("max_total_risk_pct")),
        ("daily_loss_limit_pct", status.get("daily_loss_limit_pct"), expected.get("daily_loss_limit_pct")),
        ("weekly_loss_limit_pct", status.get("weekly_loss_limit_pct"), expected.get("weekly_loss_limit_pct")),
    ]

    ok = True
    for name, actual, exp in checks:
        if actual == exp:
            print(f"OK {name}: {actual}")
        else:
            print(f"FAIL {name}: {actual} (expected {exp})")
            ok = False

    print("")
    if ok:
        print(f"PASS all limits match profile '{active}'")
        return 0
    print(f"FAIL risk guardian does not match profile '{active}'")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

