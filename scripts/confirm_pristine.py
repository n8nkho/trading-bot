#!/usr/bin/env python3
"""
Pristine verification: run key imports and one strategy to confirm the bot is in good shape.
Run from project root: python3 scripts/confirm_pristine.py
"""
import os
import sys
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def run(cmd, desc):
    r = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True, timeout=120)
    ok = r.returncode == 0
    print(f"   {'✅' if ok else '❌'} {desc}")
    if not ok and r.stderr:
        for line in r.stderr.strip().splitlines()[-3:]:
            print(f"      {line}")
    return ok


def main():
    print("=" * 60)
    print("PRISTINE VERIFICATION")
    print("=" * 60)

    all_ok = True

    print("\n1. Critical imports (no crash):")
    try:
        from agents.exit_monitor import monitor_positions
        print("   ✅ exit_monitor.monitor_positions")
    except Exception as e:
        print(f"   ❌ exit_monitor: {e}")
        all_ok = False
    try:
        from agents.risk_guardian import get_risk_status
        print("   ✅ risk_guardian.get_risk_status")
    except Exception as e:
        print(f"   ❌ risk_guardian: {e}")
        all_ok = False
    try:
        from agents.performance_analyzer import analyze_performance
        print("   ✅ performance_analyzer.analyze_performance")
    except Exception as e:
        print(f"   ❌ performance_analyzer: {e}")
        all_ok = False

    print("\n2. Strategies (exit 0):")
    if not run([sys.executable, "run_strategies.py", "inefficiency"], "run_strategies.py inefficiency"):
        all_ok = False
    if not run([sys.executable, "run_strategies.py", "sector"], "run_strategies.py sector"):
        all_ok = False

    print("\n3. Health check:")
    if not run([sys.executable, "check_health.py"], "check_health.py"):
        all_ok = False

    print("\n" + "=" * 60)
    if all_ok:
        print("✅ Pristine verification passed.")
    else:
        print("❌ Some checks failed. Review output above.")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    os.chdir(_ROOT)
    sys.exit(main())
