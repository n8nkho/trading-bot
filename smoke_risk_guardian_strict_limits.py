#!/usr/bin/env python3
"""Smoke: policy profiles cannot loosen strict-mode risk limits."""
from __future__ import annotations

from agents import risk_guardian as rg


def main() -> int:
    rg.get_profile_bundle = lambda: {
        "active_profile": "opportunistic",
        "risk": {
            "max_positions": 6,
            "max_position_size_pct": 3.5,
            "max_total_risk_pct": 8.0,
            "daily_loss_limit_pct": -2.0,
            "weekly_loss_limit_pct": -5.0,
        },
    }
    strict = rg.get_risk_limits(strict_mode=True)
    assert strict["max_positions"] == rg.STRICT_MODE_MAX_POSITIONS, strict
    assert strict["max_position_size_pct"] == rg.STRICT_MODE_MAX_POSITION_SIZE_PCT, strict
    assert strict["max_total_risk_pct"] == rg.STRICT_MODE_MAX_TOTAL_RISK_PCT, strict
    assert strict["daily_loss_limit_pct"] == rg.STRICT_MODE_DAILY_LOSS_LIMIT_PCT, strict
    assert strict["weekly_loss_limit_pct"] == rg.STRICT_MODE_WEEKLY_LOSS_LIMIT_PCT, strict

    rg.get_profile_bundle = lambda: {
        "active_profile": "capital_preservation",
        "risk": {
            "max_positions": 3,
            "max_position_size_pct": 1.5,
            "max_total_risk_pct": 4.0,
            "daily_loss_limit_pct": -0.5,
            "weekly_loss_limit_pct": -1.0,
        },
    }
    tighter = rg.get_risk_limits(strict_mode=True)
    assert tighter["max_positions"] == 3, tighter
    assert tighter["max_position_size_pct"] == 1.5, tighter
    assert tighter["max_total_risk_pct"] == 4.0, tighter
    assert tighter["daily_loss_limit_pct"] == -0.5, tighter
    assert tighter["weekly_loss_limit_pct"] == -1.0, tighter

    print("[OK] smoke_risk_guardian_strict_limits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
