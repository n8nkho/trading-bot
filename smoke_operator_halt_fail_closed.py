#!/usr/bin/env python3
"""Smoke: corrupt operator halt file fails closed."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from utils import operator_halt


def main() -> int:
    td = Path(tempfile.mkdtemp())
    original = operator_halt.HALT_PATH
    try:
        operator_halt.HALT_PATH = td / "operator_trading_halt.json"
        operator_halt.HALT_PATH.write_text("{broken json", encoding="utf-8")
        assert operator_halt.is_trading_halted() is True
        state = operator_halt.get_halt_state()
        assert state["effective_halted"] is True, state
        assert state["file_error"], state
    finally:
        operator_halt.HALT_PATH = original
        shutil.rmtree(td, ignore_errors=True)

    print("[OK] smoke_operator_halt_fail_closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
