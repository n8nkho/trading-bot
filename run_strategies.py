#!/usr/bin/env python3
"""
Legacy strategy runner (cron compatibility).

**Without** ``--execute``: no-op exit 0 (safe for health checks).

**With** ``--execute``: dispatches to the real orchestrator workflows:

- **Autonomous vs human-in-the-loop** for *new entries* is controlled by
  ``FORTRESS_EXECUTION_MODE`` (see ``utils/execution_mode.py`` and
  ``docs/OPERATOR_RUNBOOKS.md``). This script does not change that — it only
  invokes the orchestrator.

Legacy cron labels (Oracle / older installs) map to:

| Label          | Orchestrator command                                      |
|----------------|-----------------------------------------------------------|
| trump          | ``screen`` (full daily pipeline)                          |
| inefficiency   | ``screen``                                                |
| sector         | ``screen``                                                |
| smartmoney     | ``screen``                                                |
| mergerarb      | ``screen``                                                |
| momentum       | ``snipe`` (intraday sniper; uses portfolio value below)   |

You may also pass through: ``screen``, ``monitor``, ``fortress``, ``snipe`` directly.

Portfolio sizing for ``screen`` / ``snipe`` uses ``FORTRESS_PORTFOLIO_VALUE`` or
``PORTFOLIO_VALUE`` env, else ``50000``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _portfolio_arg() -> str:
    for key in ("FORTRESS_PORTFOLIO_VALUE", "PORTFOLIO_VALUE"):
        v = os.environ.get(key)
        if v and str(v).strip():
            return str(v).strip()
    return "50000"


def _normalize(name: str) -> str:
    n = name.strip().lower().replace("-", "_")
    aliases = {"merger_arb": "mergerarb", "smart_money": "smartmoney"}
    return aliases.get(n, n)


def _resolve_command(strategy: str) -> tuple[str, list[str]]:
    """
    Return (orchestrator_subcommand, extra_argv).
    """
    n = _normalize(strategy)
    if n in {"screen", "monitor", "fortress", "snipe", "architect", "review", "execute_pending"}:
        if n in {"screen", "snipe"}:
            return n, [_portfolio_arg()]
        return n, []

    legacy_screen = {
        "trump",
        "inefficiency",
        "sector",
        "smartmoney",
        "mergerarb",
    }
    if n in legacy_screen:
        return "screen", [_portfolio_arg()]
    if n == "momentum":
        return "snipe", [_portfolio_arg()]

    raise ValueError(f"Unknown strategy label: {strategy!r}")


def main(argv: list[str]) -> int:
    ts = datetime.now().isoformat(timespec="seconds")

    if len(argv) < 2 or not argv[1].strip():
        print("Usage: python3 run_strategies.py <strategy> [--execute]")
        print("Legacy labels: trump, momentum, inefficiency, sector, smartmoney, mergerarb")
        print("Direct: screen, monitor, fortress, snipe, architect, review, execute_pending")
        return 0

    strategy = argv[1].strip()
    execute = "--execute" in argv

    print(f"[run_strategies] {ts} strategy={strategy} execute={execute}")

    if not execute:
        print(f"[run_strategies] No-op (legacy cron satisfied): {strategy}")
        return 0

    try:
        sub, extras = _resolve_command(strategy)
    except ValueError as e:
        print(f"[run_strategies] ERROR: {e}")
        return 1

    root = Path(__file__).resolve().parent
    orch = root / "orchestrator.py"
    if not orch.is_file():
        print(f"[run_strategies] ERROR: missing {orch}")
        return 1

    cmd = [sys.executable, str(orch), sub, *extras]
    print(f"[run_strategies] dispatch: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(root))
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
