#!/usr/bin/env python3
"""Smoke: strict-mode risk limits cannot be loosened by policy profiles."""

from __future__ import annotations

import agents.risk_guardian as rg


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

    normal = rg.get_risk_limits(strict_mode=False)
    assert normal["max_positions"] == 6, normal
    assert normal["max_total_risk_pct"] == 8.0, normal

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
            "weekly_loss_limit_pct": -1.5,
        },
    }
    tighter = rg.get_risk_limits(strict_mode=True)
    assert tighter["max_positions"] == 3, tighter
    assert tighter["max_position_size_pct"] == 1.5, tighter
    assert tighter["max_total_risk_pct"] == 4.0, tighter
    assert tighter["daily_loss_limit_pct"] == -0.5, tighter
    assert tighter["weekly_loss_limit_pct"] == -1.5, tighter

    print("[smoke] smoke_risk_strict_policy_limits: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
