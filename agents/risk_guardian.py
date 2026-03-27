"""
Risk Guardian Agent - Portfolio Protection System
Monitors and enforces risk limits to protect capital
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
import json
from utils.policy_profile import get_profile_bundle
from utils.volatility_adaptive_sizing import (
    adaptive_position_size_pct,
    load_latest_vix_from_fortress_report,
)

# Setup logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "risk.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Risk limits configuration
MAX_POSITIONS = 5
MAX_POSITION_SIZE_PCT = 3.0  # % of portfolio
MAX_TOTAL_RISK_PCT = 7.0    # % of portfolio
DAILY_LOSS_LIMIT_PCT = -2.0  # % of equity
WEEKLY_LOSS_LIMIT_PCT = -5.0 # % of equity
MAX_SECTOR_CONCENTRATION_PCT = 30.0  # % of portfolio

# Circuit breaker thresholds
CIRCUIT_BREAKER_REDUCE_THRESHOLD = 3  # consecutive losses
CIRCUIT_BREAKER_HALT_THRESHOLD = 5    # consecutive losses

# Strict "risk elimination" profile (triggered only when system is already under stress).
# Goal: prevent capital drawdown while hedging/strategies are expected to stabilize risk.
STRICT_MODE_MAX_POSITIONS = 4
STRICT_MODE_MAX_POSITION_SIZE_PCT = 2.0
STRICT_MODE_MAX_TOTAL_RISK_PCT = 5.0
STRICT_MODE_DAILY_LOSS_LIMIT_PCT = -1.0
STRICT_MODE_WEEKLY_LOSS_LIMIT_PCT = -2.0
STRICT_MODE_CIRCUIT_BREAKER_REDUCE_THRESHOLD = 2
STRICT_MODE_CIRCUIT_BREAKER_HALT_THRESHOLD = 4

# Track consecutive losses (in-memory for now)
consecutive_losses = 0
circuit_breaker_active = False
position_size_reduction = 1.0  # multiplier for position sizing

STATE_FILE = Path("data") / "risk_guardian_state.json"

# If enabled, automatically clears persisted circuit-breaker state after a time window,
# so a single losing streak doesn't permanently require operator intervention.
#
# - Default: ON
# - Disable: FORTRESS_AUTO_RESET_RISK_GUARDIAN_STATE=0
AUTO_RESET_RISK_GUARDIAN_STATE = str(os.getenv("FORTRESS_AUTO_RESET_RISK_GUARDIAN_STATE", "1")).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
RISK_STATE_MAX_AGE_HOURS = float(os.getenv("FORTRESS_RISK_STATE_MAX_AGE_HOURS", "24"))


def _policy_bundle() -> dict:
    """
    Return active policy bundle with safe fallbacks.
    """
    try:
        bundle = get_profile_bundle()
        if isinstance(bundle, dict):
            return bundle
    except Exception as e:
        logger.warning(f"Policy profile unavailable, falling back to built-ins: {type(e).__name__}: {str(e)}")
    return {"active_profile": "balanced", "risk": {}}


def _policy_risk_limits() -> dict:
    """
    Source-of-truth profile limits from config/policy_profiles.json.
    These are the configured policy limits (without volatility adaptation).
    """
    bundle = _policy_bundle()
    risk_cfg = bundle.get("risk") or {}
    profile_name = bundle.get("active_profile") or "balanced"
    out = {
        "max_positions": int(risk_cfg.get("max_positions", MAX_POSITIONS)),
        "max_position_size_pct": float(risk_cfg.get("max_position_size_pct", MAX_POSITION_SIZE_PCT)),
        "max_total_risk_pct": float(risk_cfg.get("max_total_risk_pct", MAX_TOTAL_RISK_PCT)),
        "daily_loss_limit_pct": float(risk_cfg.get("daily_loss_limit_pct", DAILY_LOSS_LIMIT_PCT)),
        "weekly_loss_limit_pct": float(risk_cfg.get("weekly_loss_limit_pct", WEEKLY_LOSS_LIMIT_PCT)),
        "policy_profile": str(profile_name),
    }
    logger.info(
        "Loaded risk policy profile '%s' limits: max_positions=%s, max_position_size_pct=%s, max_total_risk_pct=%s",
        out["policy_profile"],
        out["max_positions"],
        out["max_position_size_pct"],
        out["max_total_risk_pct"],
    )
    return out


def _load_risk_state() -> None:
    """
    Load persisted risk state so the circuit breaker isn't lost on restart.
    """
    global consecutive_losses, circuit_breaker_active, position_size_reduction
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            consecutive_losses = int(data.get("consecutive_losses", 0) or 0)
            circuit_breaker_active = bool(data.get("circuit_breaker_active", False))
            position_size_reduction = float(data.get("position_size_reduction", 1.0) or 1.0)
            state_profile = str(data.get("policy_profile") or "").strip().lower()
            active_profile = str(_policy_bundle().get("active_profile") or "").strip().lower()
            if state_profile and active_profile and state_profile != active_profile:
                logger.info(
                    "Risk state profile changed from '%s' to '%s'; runtime loss/circuit state kept, limits sourced from active policy.",
                    state_profile,
                    active_profile,
                )

            updated_at_raw = data.get("updated_at")
            if AUTO_RESET_RISK_GUARDIAN_STATE and updated_at_raw:
                try:
                    updated_at = datetime.fromisoformat(str(updated_at_raw))
                    age_hours = (datetime.now() - updated_at).total_seconds() / 3600.0
                    if age_hours > RISK_STATE_MAX_AGE_HOURS:
                        logger.warning(
                            "Auto-resetting risk_guardian state because persisted state is stale "
                            f"(age_hours={age_hours:.2f} > max_age_hours={RISK_STATE_MAX_AGE_HOURS})"
                        )
                        consecutive_losses = 0
                        circuit_breaker_active = False
                        position_size_reduction = 1.0
                except Exception:
                    # If parsing fails, do not reset (safer than clearing state unexpectedly).
                    pass
            logger.info(f"Loaded persisted risk state: consecutive_losses={consecutive_losses}")
    except Exception as e:
        logger.warning(f"Could not load risk state from {STATE_FILE}: {type(e).__name__}: {str(e)}")


def _persist_risk_state() -> None:
    """
    Persist risk state whenever it changes.
    """
    try:
        STATE_FILE.parent.mkdir(exist_ok=True, parents=True)
        with open(STATE_FILE, "w") as f:
            json.dump(
                {
                    "consecutive_losses": consecutive_losses,
                    "circuit_breaker_active": circuit_breaker_active,
                    "position_size_reduction": position_size_reduction,
                    "policy_profile": _policy_bundle().get("active_profile"),
                    "updated_at": datetime.now().isoformat(),
                },
                f,
                indent=2,
            )
    except Exception as e:
        logger.warning(f"Could not persist risk state to {STATE_FILE}: {type(e).__name__}: {str(e)}")


def check_risk_limits(portfolio_data, new_position, strict_mode: bool = False):
    """
    Check if a new position meets all risk management criteria.
    
    Args:
        portfolio_data: dict with keys:
            - equity: float, total account equity
            - positions: list of dicts with ticker, value, sector
            - today_pnl: float, today's P&L
            - week_pnl: float (optional), week's P&L
        new_position: dict with keys:
            - ticker: str
            - size: int, number of shares
            - value: float, position value
            - sector: str (optional)
    
    Returns:
        dict: {"approved": bool, "reason": str, "adjusted_size": float (optional)}
    """
    return check_risk_limits_with_profile(portfolio_data, new_position, strict_mode=strict_mode)


def get_risk_limits(strict_mode: bool = False) -> dict:
    """
    Return effective limits for risk evaluation.
    This does not change global state; it only affects *this* decision.
    """
    policy_limits = _policy_risk_limits()
    policy_profile = policy_limits.get("policy_profile")
    if strict_mode:
        base = {
            "max_positions": STRICT_MODE_MAX_POSITIONS,
            "max_position_size_pct": STRICT_MODE_MAX_POSITION_SIZE_PCT,
            "max_total_risk_pct": STRICT_MODE_MAX_TOTAL_RISK_PCT,
            "daily_loss_limit_pct": STRICT_MODE_DAILY_LOSS_LIMIT_PCT,
            "weekly_loss_limit_pct": STRICT_MODE_WEEKLY_LOSS_LIMIT_PCT,
            "circuit_breaker_reduce_threshold": STRICT_MODE_CIRCUIT_BREAKER_REDUCE_THRESHOLD,
            "circuit_breaker_halt_threshold": STRICT_MODE_CIRCUIT_BREAKER_HALT_THRESHOLD,
        }
    else:
        base = {
            "max_positions": policy_limits["max_positions"],
            "max_position_size_pct": policy_limits["max_position_size_pct"],
            "max_total_risk_pct": policy_limits["max_total_risk_pct"],
            "daily_loss_limit_pct": policy_limits["daily_loss_limit_pct"],
            "weekly_loss_limit_pct": policy_limits["weekly_loss_limit_pct"],
            "circuit_breaker_reduce_threshold": CIRCUIT_BREAKER_REDUCE_THRESHOLD,
            "circuit_breaker_halt_threshold": CIRCUIT_BREAKER_HALT_THRESHOLD,
        }
    # Task 2: volatility-adaptive position cap (counter-cyclical exposure).
    # Enabled by default; can be disabled with FORTRESS_VOL_ADAPTIVE_SIZING=0.
    vol_adapt_enabled = str(os.getenv("FORTRESS_VOL_ADAPTIVE_SIZING", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    vix_now = load_latest_vix_from_fortress_report(Path("data")) if vol_adapt_enabled else None
    if vol_adapt_enabled:
        new_cap, tier = adaptive_position_size_pct(
            base_position_size_pct=float(base.get("max_position_size_pct", MAX_POSITION_SIZE_PCT)),
            vix=vix_now,
        )
        base["max_position_size_pct"] = float(new_cap)
        base["volatility_adaptive_sizing"] = {
            "enabled": True,
            "vix": vix_now,
            "tier": tier.name,
            "mode": tier.mode,
            "max_position_size_pct": float(new_cap),
        }
    else:
        base["volatility_adaptive_sizing"] = {"enabled": False, "vix": None}
    base["policy_profile"] = policy_profile
    return base


def check_risk_limits_with_profile(portfolio_data, new_position, strict_mode: bool = False):
    """
    Strict-mode variant of `check_risk_limits`.
    - strict_mode tightens limits and uses a stricter circuit-breaker threshold.
    - does not alter persisted global state; it only changes approval for this decision.
    """
    logger.info(f"Checking risk limits for new position: {new_position['ticker']} (strict_mode={strict_mode})")
    
    equity = portfolio_data.get('equity', 0)
    positions = portfolio_data.get('positions', [])
    today_pnl = portfolio_data.get('today_pnl', 0)
    week_pnl = portfolio_data.get('week_pnl', None)

    limits = get_risk_limits(strict_mode=strict_mode)
    
    # Check circuit breaker status
    if strict_mode:
        if consecutive_losses >= limits["circuit_breaker_halt_threshold"]:
            return {
                "approved": False,
                "reason": f"Strict mode halt: {consecutive_losses} consecutive losses (threshold: {limits['circuit_breaker_halt_threshold']})",
            }
    else:
        circuit_check = check_circuit_breaker()
        if not circuit_check['approved']:
            logger.warning(f"Circuit breaker triggered: {circuit_check['reason']}")
            return circuit_check
    
    # Apply position size reduction for this decision only.
    if strict_mode:
        effective_reduction = 0.5 if consecutive_losses >= limits["circuit_breaker_reduce_threshold"] else 1.0
    else:
        effective_reduction = position_size_reduction

    adjusted_value = new_position["value"] * effective_reduction
    if effective_reduction < 1.0:
        logger.info(f"Position size reduced by {(1-effective_reduction)*100:.0f}% due to consecutive losses (strict_mode={strict_mode})")
    
    # 1. Check max concurrent positions
    max_positions = limits["max_positions"]
    if len(positions) >= max_positions:
        reason = f"Maximum {max_positions} concurrent positions reached. Current: {len(positions)}"
        logger.warning(reason)
        return {"approved": False, "reason": reason}
    
    # 2. Check position size limit
    position_pct = (adjusted_value / equity) * 100
    if position_pct > limits["max_position_size_pct"]:
        reason = f"Position size {position_pct:.2f}% exceeds {limits['max_position_size_pct']}% limit"
        logger.warning(reason)
        return {"approved": False, "reason": reason}
    
    # 3. Check total portfolio risk
    total_position_value = sum(p.get('value', 0) for p in positions) + adjusted_value
    total_risk_pct = (total_position_value / equity) * 100
    if total_risk_pct > limits["max_total_risk_pct"]:
        reason = f"Total portfolio risk {total_risk_pct:.2f}% exceeds {limits['max_total_risk_pct']}% limit"
        logger.warning(reason)
        return {"approved": False, "reason": reason}
    
    # 4. Check daily loss limit
    daily_loss_pct = (today_pnl / equity) * 100
    if daily_loss_pct <= limits["daily_loss_limit_pct"]:
        reason = f"Daily loss limit reached: {daily_loss_pct:.2f}% (limit: {limits['daily_loss_limit_pct']}%)"
        logger.error(reason)
        return {"approved": False, "reason": reason}
    
    # 5. Check weekly loss limit (if provided)
    if week_pnl is not None:
        weekly_loss_pct = (week_pnl / equity) * 100
        if weekly_loss_pct <= limits["weekly_loss_limit_pct"]:
            reason = f"Weekly loss limit reached: {weekly_loss_pct:.2f}% (limit: {limits['weekly_loss_limit_pct']}%)"
            logger.error(reason)
            return {"approved": False, "reason": reason}
    
    # 6. Check sector concentration
    sector_check = check_sector_concentration(positions, new_position, equity, adjusted_value)
    if not sector_check['approved']:
        logger.warning(sector_check['reason'])
        return sector_check
    
    # All checks passed
    logger.info(f"Position approved: {new_position['ticker']} - {position_pct:.2f}% of portfolio")
    
    result = {
        "approved": True,
        "reason": f"All risk checks passed. Position size: {position_pct:.2f}% of portfolio"
    }
    
    if effective_reduction < 1.0:
        result["adjusted_size"] = new_position["size"] * effective_reduction
        result["reason"] += f" (size reduced {(1-effective_reduction)*100:.0f}% due to consecutive losses)"
    
    return result


def check_sector_concentration(positions, new_position, equity, new_position_value):
    """
    Check if adding new position would exceed sector concentration limits.
    
    Args:
        positions: list of existing positions
        new_position: dict with new position details
        equity: total account equity
        new_position_value: adjusted value of new position
    
    Returns:
        dict: {"approved": bool, "reason": str}
    """
    new_sector = new_position.get('sector', 'Unknown')
    
    # Calculate current sector exposure
    sector_exposure = {}
    for pos in positions:
        sector = pos.get('sector', 'Unknown')
        value = pos.get('value', 0)
        sector_exposure[sector] = sector_exposure.get(sector, 0) + value
    
    # Add new position to sector exposure
    sector_exposure[new_sector] = sector_exposure.get(new_sector, 0) + new_position_value
    
    # Check if any sector exceeds limit
    for sector, value in sector_exposure.items():
        sector_pct = (value / equity) * 100
        if sector_pct > MAX_SECTOR_CONCENTRATION_PCT:
            reason = f"Sector '{sector}' concentration {sector_pct:.2f}% exceeds {MAX_SECTOR_CONCENTRATION_PCT}% limit"
            return {"approved": False, "reason": reason}
    
    return {"approved": True, "reason": "Sector concentration within limits"}


def check_circuit_breaker():
    """
    Check circuit breaker status based on consecutive losses.
    
    Returns:
        dict: {"approved": bool, "reason": str}
    """
    global circuit_breaker_active
    
    if consecutive_losses >= CIRCUIT_BREAKER_HALT_THRESHOLD:
        circuit_breaker_active = True
        reason = f"Trading halted: {consecutive_losses} consecutive losses (threshold: {CIRCUIT_BREAKER_HALT_THRESHOLD})"
        return {"approved": False, "reason": reason}
    
    return {"approved": True, "reason": "Circuit breaker OK"}


def update_consecutive_losses(trade_result):
    """
    Update consecutive loss counter based on trade result.
    
    Args:
        trade_result: dict with 'pnl' key (positive = profit, negative = loss)
    """
    global consecutive_losses, position_size_reduction, circuit_breaker_active
    
    pnl = trade_result.get('pnl', 0)
    
    if pnl < 0:
        consecutive_losses += 1
        logger.warning(f"Consecutive losses: {consecutive_losses}")
        
        # Apply position size reduction
        if consecutive_losses >= CIRCUIT_BREAKER_REDUCE_THRESHOLD:
            position_size_reduction = 0.5
            logger.warning(f"Position size reduced to 50% after {consecutive_losses} consecutive losses")
        
        # Activate circuit breaker halt
        if consecutive_losses >= CIRCUIT_BREAKER_HALT_THRESHOLD:
            circuit_breaker_active = True
            logger.error(f"CIRCUIT BREAKER ACTIVATED: Trading halted after {consecutive_losses} consecutive losses")
    else:
        # Reset on profitable trade
        if consecutive_losses > 0:
            logger.info(f"Consecutive loss streak broken. Resetting from {consecutive_losses} to 0")
        consecutive_losses = 0
        position_size_reduction = 1.0
        circuit_breaker_active = False

    _persist_risk_state()


def reset_circuit_breaker():
    """
    Manually reset circuit breaker (e.g., after review/intervention).
    """
    global consecutive_losses, position_size_reduction, circuit_breaker_active
    
    logger.info("Circuit breaker manually reset")
    consecutive_losses = 0
    position_size_reduction = 1.0
    circuit_breaker_active = False
    _persist_risk_state()


def get_risk_status():
    """
    Get current risk management status.
    
    Returns:
        dict: Current risk status including circuit breaker state
    """
    policy_limits = _policy_risk_limits()
    effective_limits = get_risk_limits(strict_mode=False)
    return {
        "consecutive_losses": consecutive_losses,
        "position_size_reduction": position_size_reduction,
        "circuit_breaker_active": circuit_breaker_active,
        "max_positions": policy_limits["max_positions"],
        "max_position_size_pct": policy_limits["max_position_size_pct"],
        "max_total_risk_pct": policy_limits["max_total_risk_pct"],
        "daily_loss_limit_pct": policy_limits["daily_loss_limit_pct"],
        "weekly_loss_limit_pct": policy_limits["weekly_loss_limit_pct"],
        "max_sector_concentration_pct": MAX_SECTOR_CONCENTRATION_PCT,
        "policy_profile": policy_limits["policy_profile"],
        "effective_max_position_size_pct": effective_limits.get("max_position_size_pct"),
        "volatility_adaptive_sizing": effective_limits.get("volatility_adaptive_sizing"),
    }


# Load persisted state at import time.
_load_risk_state()


# Example usage and testing
if __name__ == "__main__":
    # Self-test note:
    # Risk Guardian should be tested via an external harness using real positions.
    # This module intentionally contains no hard-coded ticker examples.
    print("risk_guardian self-test: no hard-coded ticker examples in this build.")
