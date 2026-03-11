"""
Barbell Portfolio Manager
90% safe (T-bills/cash) + 10% speculative active trading.
Structural loss floor: even if 100% of active positions go to zero,
T-bill yield partially offsets the loss.
"""
import logging
import json
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)
DATA_DIR = Path("data")
BARBELL_FILE = DATA_DIR / "barbell_state.json"

SPECULATIVE_PCT = 0.10
SAFE_TICKER = "SGOV"


def get_barbell_limits(portfolio_equity):
    """Return current barbell allocation limits."""
    active_budget = portfolio_equity * SPECULATIVE_PCT
    safe_allocation = portfolio_equity * (1 - SPECULATIVE_PCT)
    return {
        "portfolio_equity": portfolio_equity,
        "active_budget": round(active_budget, 2),
        "safe_allocation": round(safe_allocation, 2),
        "speculative_pct": SPECULATIVE_PCT,
        "safe_ticker": SAFE_TICKER,
        "timestamp": datetime.now().isoformat(),
    }


def check_active_budget_remaining(portfolio_equity, current_active_value):
    """How much active budget remains?"""
    limits = get_barbell_limits(portfolio_equity)
    remaining = max(0.0, limits["active_budget"] - current_active_value)
    utilization = current_active_value / max(limits["active_budget"], 1.0)
    return {
        "remaining_budget": round(remaining, 2),
        "active_budget": limits["active_budget"],
        "current_active_value": current_active_value,
        "utilization_pct": round(utilization * 100, 1),
        "budget_available": remaining > 50.0,
    }


def log_barbell_status(portfolio_equity, current_active_value):
    """Log and persist current barbell status."""
    status = check_active_budget_remaining(portfolio_equity, current_active_value)
    status["portfolio_equity"] = portfolio_equity
    status["timestamp"] = datetime.now().isoformat()
    try:
        DATA_DIR.mkdir(exist_ok=True)
        BARBELL_FILE.write_text(json.dumps(status, indent=2))
    except Exception as e:
        logger.error(f"Failed to save barbell state: {e}")
    logger.info(
        f"Barbell: equity=${portfolio_equity:,.0f} | "
        f"active=${current_active_value:,.0f}/{status['active_budget']:,.0f} "
        f"({status['utilization_pct']:.0f}%) | remaining=${status['remaining_budget']:,.0f}"
    )
    return status
