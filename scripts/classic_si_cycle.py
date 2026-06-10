#!/usr/bin/env python3
"""Run Classic autonomous SI cycle (ingest fortress gaps + screener relax)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def main() -> int:
    from utils.classic_si_autonomous import run_classic_si_cycle

    out = run_classic_si_cycle()
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
