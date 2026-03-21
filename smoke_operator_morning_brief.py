#!/usr/bin/env python3
"""Smoke: operator morning brief builds (no network if macro cache cold may hit yfinance)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from utils.operator_morning_brief import build_operator_morning_brief


def main() -> int:
    td = Path(tempfile.mkdtemp())
    try:
        data = td / "data"
        data.mkdir()
        (data / "positions.json").write_text('[{"ticker":"SPY","qty":1}]', encoding="utf-8")
        b = build_operator_morning_brief(
            data_dir=data,
            health_excerpt={"cron_configured": True, "cron_count": 2, "validation_errors": []},
            safety_excerpt={"circuit_breaker_active": False},
        )
        assert "calendar" in b and "macro" in b
        assert "stack" in b and "book" in b
        assert b.get("disclaimer")
        assert isinstance(b["book"], list)
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)

    print("[OK] smoke_operator_morning_brief")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
