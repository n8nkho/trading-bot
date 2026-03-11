"""
Risk Guardian Agent - Portfolio Protection System
Monitors and enforces risk limits to protect capital
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

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
MAX_POSITION_SIZE_PCT = 5.0  # % of portfolio
MAX_TOTAL_RISK_PCT = 10.0    # % of portfolio
DAILY_LOSS_LIMIT_PCT = -2.0  # % of equity
WEEKLY_LOSS_LIMIT_PCT = -5.0 # % of equity
MAX_SECTOR_CONCENTRATION_PCT = 30.0  # % of portfolio

# Circuit breaker thresholds
CIRCUIT_BREAKER_REDUCE_THRESHOLD = 3  # consecutive losses
CIRCUIT_BREAKER_HALT_THRESHOLD = 5    # consecutive losses

# Track consecutive losses (persisted to disk)
consecutive_losses = 0
circuit_breaker_active = False
position_size_reduction = 1.0  # multiplier for position sizing

RISK_STATE_FILE = Path("data/risk_state.json")


def _save_risk_state():
    state = {
        "consecutive_losses": consecutive_losses,
        "circuit_breaker_active": circuit_breaker_active,
        "position_size_reduction": position_size_reduction,
        "last_updated": datetime.now().isoformat()
    }
    try:
        RISK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RISK_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save risk state: {e}")


def _load_risk_state():
    global consecutive_losses, circuit_breaker_active, position_size_reduction
    try:
        if RISK_STATE_FILE.exists():
            with open(RISK_STATE_FILE) as f:
                state = json.load(f)
            consecutive_losses = state.get("consecutive_losses", 0)
            circuit_breaker_active = state.get("circuit_breaker_active", False)
            position_size_reduction = state.get("position_size_reduction", 1.0)
            logger.info(f"Loaded risk state: {consecutive_losses} consecutive losses, breaker={circuit_breaker_active}")
    except Exception as e:
        logger.error(f"Could not load risk state: {e}")


_load_risk_state()


def check_portfolio_correlation(new_ticker: str, existing_tickers: list, lookback_days: int = 60, max_avg_corr: float = 0.70) -> dict:
    """
    Block entry if new position would increase average portfolio correlation above threshold.
    Returns {"approved": bool, "reason": str, "avg_correlation": float}
    """
    if not existing_tickers:
        return {"approved": True, "reason": "No existing positions to correlate with", "avg_correlation": 0.0}
    try:
        import yfinance as yf
        import numpy as np
        all_tickers = existing_tickers + [new_ticker]
        data = yf.download(all_tickers, period=f"{lookback_days}d", auto_adjust=True, progress=False)["Close"]
        if data.empty or new_ticker not in data.columns:
            return {"approved": True, "reason": "Could not fetch correlation data", "avg_correlation": 0.0}
        returns = data.pct_change().dropna()
        if len(returns) < 20:
            return {"approved": True, "reason": "Insufficient data for correlation", "avg_correlation": 0.0}
        corr_matrix = returns.corr()
        new_ticker_corrs = corr_matrix[new_ticker].drop(new_ticker)
        avg_corr = float(new_ticker_corrs.abs().mean())
        if avg_corr > max_avg_corr:
            return {
                "approved": False,
                "reason": f"{new_ticker} avg correlation {avg_corr:.2f} with existing book exceeds {max_avg_corr} limit",
                "avg_correlation": avg_corr
            }
        return {"approved": True, "reason": f"Correlation OK ({avg_corr:.2f})", "avg_correlation": avg_corr}
    except Exception as e:
        logger.warning(f"Correlation check failed, allowing trade: {e}")
        return {"approved": True, "reason": f"Correlation check error (allowing): {e}", "avg_correlation": 0.0}


def check_risk_limits(portfolio_data, new_position):
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
    logger.info(f"Checking risk limits for new position: {new_position['ticker']}")
    
    equity = portfolio_data.get('equity', 0)
    positions = portfolio_data.get('positions', [])
    today_pnl = portfolio_data.get('today_pnl', 0)
    week_pnl = portfolio_data.get('week_pnl', None)
    
    # Check circuit breaker status
    circuit_check = check_circuit_breaker()
    if not circuit_check['approved']:
        logger.warning(f"Circuit breaker triggered: {circuit_check['reason']}")
        return circuit_check
    
    # Apply position size reduction if circuit breaker is in reduce mode
    adjusted_value = new_position['value'] * position_size_reduction
    if position_size_reduction < 1.0:
        logger.info(f"Position size reduced by {(1-position_size_reduction)*100:.0f}% due to consecutive losses")
    
    # 1. Check max concurrent positions
    if len(positions) >= MAX_POSITIONS:
        reason = f"Maximum {MAX_POSITIONS} concurrent positions reached. Current: {len(positions)}"
        logger.warning(reason)
        return {"approved": False, "reason": reason}
    
    # 2. Check position size limit
    position_pct = (adjusted_value / equity) * 100
    if position_pct > MAX_POSITION_SIZE_PCT:
        reason = f"Position size {position_pct:.2f}% exceeds {MAX_POSITION_SIZE_PCT}% limit"
        logger.warning(reason)
        return {"approved": False, "reason": reason}
    
    # 3. Check total portfolio risk
    total_position_value = sum(p.get('value', 0) for p in positions) + adjusted_value
    total_risk_pct = (total_position_value / equity) * 100
    if total_risk_pct > MAX_TOTAL_RISK_PCT:
        reason = f"Total portfolio risk {total_risk_pct:.2f}% exceeds {MAX_TOTAL_RISK_PCT}% limit"
        logger.warning(reason)
        return {"approved": False, "reason": reason}
    
    # 4. Check daily loss limit
    daily_loss_pct = (today_pnl / equity) * 100
    if daily_loss_pct <= DAILY_LOSS_LIMIT_PCT:
        reason = f"Daily loss limit reached: {daily_loss_pct:.2f}% (limit: {DAILY_LOSS_LIMIT_PCT}%)"
        logger.error(reason)
        return {"approved": False, "reason": reason}
    
    # 5. Check weekly loss limit (if provided)
    if week_pnl is not None:
        weekly_loss_pct = (week_pnl / equity) * 100
        if weekly_loss_pct <= WEEKLY_LOSS_LIMIT_PCT:
            reason = f"Weekly loss limit reached: {weekly_loss_pct:.2f}% (limit: {WEEKLY_LOSS_LIMIT_PCT}%)"
            logger.error(reason)
            return {"approved": False, "reason": reason}
    
    # 6. Check sector concentration
    sector_check = check_sector_concentration(positions, new_position, equity, adjusted_value)
    if not sector_check['approved']:
        logger.warning(sector_check['reason'])
        return sector_check

    # 7. Check portfolio correlation
    existing_tickers = [p.get("ticker") for p in positions if p.get("ticker")]
    if existing_tickers:
        corr_check = check_portfolio_correlation(new_position["ticker"], existing_tickers)
        if not corr_check["approved"]:
            logger.warning(corr_check["reason"])
            return {"approved": False, "reason": corr_check["reason"]}

    # All checks passed
    logger.info(f"Position approved: {new_position['ticker']} - {position_pct:.2f}% of portfolio")
    
    result = {
        "approved": True,
        "reason": f"All risk checks passed. Position size: {position_pct:.2f}% of portfolio"
    }
    
    if position_size_reduction < 1.0:
        result['adjusted_size'] = new_position['size'] * position_size_reduction
        result['reason'] += f" (size reduced {(1-position_size_reduction)*100:.0f}% due to consecutive losses)"
    
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
    _save_risk_state()


def reset_circuit_breaker():
    """
    Manually reset circuit breaker (e.g., after review/intervention).
    """
    global consecutive_losses, position_size_reduction, circuit_breaker_active
    
    logger.info("Circuit breaker manually reset")
    consecutive_losses = 0
    position_size_reduction = 1.0
    circuit_breaker_active = False
    _save_risk_state()


def get_risk_status():
    """
    Get current risk management status.
    
    Returns:
        dict: Current risk status including circuit breaker state
    """
    return {
        "consecutive_losses": consecutive_losses,
        "position_size_reduction": position_size_reduction,
        "circuit_breaker_active": circuit_breaker_active,
        "max_positions": MAX_POSITIONS,
        "max_position_size_pct": MAX_POSITION_SIZE_PCT,
        "max_total_risk_pct": MAX_TOTAL_RISK_PCT,
        "daily_loss_limit_pct": DAILY_LOSS_LIMIT_PCT,
        "weekly_loss_limit_pct": WEEKLY_LOSS_LIMIT_PCT,
        "max_sector_concentration_pct": MAX_SECTOR_CONCENTRATION_PCT
    }


# Example usage and testing
if __name__ == "__main__":
    # Mock portfolio data
    mock_portfolio = {
        "equity": 100000,
        "positions": [
            {"ticker": "AAPL", "value": 3000, "sector": "Technology"},
            {"ticker": "MSFT", "value": 2500, "sector": "Technology"}
        ],
        "today_pnl": -500,
        "week_pnl": -1000
    }
    
    # Mock new position
    mock_position = {
        "ticker": "GOOGL",
        "size": 10,
        "value": 4000,
        "sector": "Technology"
    }
    
    # Test risk check
    result = check_risk_limits(mock_portfolio, mock_position)
    print(f"\nRisk Check Result: {result}")
    
    # Test circuit breaker
    print(f"\nInitial Risk Status: {get_risk_status()}")
    
    # Simulate consecutive losses
    for i in range(6):
        update_consecutive_losses({"pnl": -100})
        print(f"\nAfter loss {i+1}: {get_risk_status()}")
        
        # Try to place a trade
        result = check_risk_limits(mock_portfolio, mock_position)
        print(f"Trade approval: {result}")
