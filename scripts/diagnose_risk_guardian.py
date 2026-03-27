#!/usr/bin/env python3
"""
Diagnose risk guardian policy profile loading.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POLICY_FILE = ROOT / "config" / "policy_profiles.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_policy() -> dict:
    with open(POLICY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    from agents.risk_guardian import get_risk_status

    print("=" * 70)
    print("RISK GUARDIAN POLICY PROFILE DIAGNOSTIC")
    print("=" * 70)

    print("\n1) Loading policy profile config...")
    cfg = _load_policy()
    active = str(cfg.get("active_profile") or "balanced")
    profiles = cfg.get("profiles") or {}
    expected = ((profiles.get(active) or {}).get("risk") or {})
    print(f"   Active profile: {active}")
    print(f"   Expected max_positions: {expected.get('max_positions')}")
    print(f"   Expected max_position_size_pct: {expected.get('max_position_size_pct')}")
    print(f"   Expected max_total_risk_pct: {expected.get('max_total_risk_pct')}")

    print("\n2) Loading risk guardian status...")
    status = get_risk_status()
    print(f"   Loaded profile: {status.get('policy_profile')}")
    print(f"   Actual max_positions: {status.get('max_positions')}")
    print(f"   Actual max_position_size_pct: {status.get('max_position_size_pct')}")
    print(f"   Actual max_total_risk_pct: {status.get('max_total_risk_pct')}")
    print(f"   Effective max_position_size_pct: {status.get('effective_max_position_size_pct')}")

    print("\n3) Validation...")
    issues: list[str] = []

    checks = [
        ("max_positions", status.get("max_positions"), expected.get("max_positions")),
        ("max_position_size_pct", status.get("max_position_size_pct"), expected.get("max_position_size_pct")),
        ("max_total_risk_pct", status.get("max_total_risk_pct"), expected.get("max_total_risk_pct")),
    ]
    for name, actual, exp in checks:
        if actual == exp:
            print(f"   OK {name}: {actual}")
        else:
            issues.append(f"{name} mismatch: {actual} != {exp}")

    print("\n" + "=" * 70)
    if issues:
        print("FAIL: POLICY LOADING IS BROKEN")
        print("=" * 70)
        for issue in issues:
            print(f"   - {issue}")
        return 1

    print("PASS: POLICY LOADING IS WORKING CORRECTLY")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

