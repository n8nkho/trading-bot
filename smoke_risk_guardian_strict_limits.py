#!/usr/bin/env python3
"""Regression: strict mode policy profiles must not loosen stress risk caps."""

import os

os.environ["TRADING_POLICY_PROFILE"] = "opportunistic"

from agents import risk_guardian


def main() -> int:
    limits = risk_guardian.get_risk_limits(strict_mode=True)
    assert limits["max_positions"] <= risk_guardian.STRICT_MODE_MAX_POSITIONS, limits
    assert limits["max_position_size_pct"] <= risk_guardian.STRICT_MODE_MAX_POSITION_SIZE_PCT, limits
    assert limits["max_total_risk_pct"] <= risk_guardian.STRICT_MODE_MAX_TOTAL_RISK_PCT, limits
    assert limits["daily_loss_limit_pct"] >= risk_guardian.STRICT_MODE_DAILY_LOSS_LIMIT_PCT, limits
    assert limits["weekly_loss_limit_pct"] >= risk_guardian.STRICT_MODE_WEEKLY_LOSS_LIMIT_PCT, limits
    print("PASS: strict risk limits cannot be loosened by policy profile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
