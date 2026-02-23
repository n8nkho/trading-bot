import yfinance as yf
from alpaca_trade_api import REST
import logging

# Constants
RISK_ON_BOND_PCT = 0.15
RISK_OFF_BOND_PCT = 0.40
BONDS_TICKER = "TLT"

# Initialize Alpaca API
alpaca = REST()

def get_market_regime():
    vix_data = yf.Ticker("^VIX").history(period="1d")
    current_vix = vix_data['Close'].iloc[-1]
    spy_data = yf.Ticker("SPY").history(period="200d")
    spy_50ma = spy_data['Close'].rolling(window=50).mean().iloc[-1]
    spy_200ma = spy_data['Close'].rolling(window=200).mean().iloc[-1]
    spy_current = spy_data['Close'].iloc[-1]

    if current_vix < 15 and spy_current > spy_200ma:
        return "RISK_ON"
    elif current_vix > 25 or spy_current < spy_200ma:
        return "RISK_OFF"
    else:
        return "NEUTRAL"

def calculate_bond_target(portfolio_value, market_regime):
    if market_regime == "RISK_ON":
        target = portfolio_value * RISK_ON_BOND_PCT
    elif market_regime == "RISK_OFF":
        target = portfolio_value * RISK_OFF_BOND_PCT
    else:
        target = portfolio_value * 0.25
    return target

def get_current_bond_position():
    try:
        position = alpaca.get_position(BONDS_TICKER)
        return position.qty, position.market_value
    except Exception:
        return 0, 0

def rebalance_bonds(portfolio_value):
    market_regime = get_market_regime()
    target_allocation = calculate_bond_target(portfolio_value, market_regime)
    current_qty, current_value = get_current_bond_position()
    diff = target_allocation - current_value

    orders = []
    if diff > 0:
        orders.append({'action': 'buy', 'qty': diff / 100, 'ticker': BONDS_TICKER})
    elif diff < 0:
        orders.append({'action': 'sell', 'qty': -diff / 100, 'ticker': BONDS_TICKER})

    logging.info(f"Rebalancing bonds: {orders}")
    return orders

def bonds_performance():
    try:
        position = alpaca.get_position(BONDS_TICKER)
        entry_price = position.avg_entry_price
        current_price = yf.Ticker(BONDS_TICKER).history(period="1d")['Close'].iloc[-1]
        pnl = (current_price - entry_price) * position.qty
        pnl_pct = (pnl / (entry_price * position.qty)) * 100
        return {'pnl': pnl, 'pnl_pct': pnl_pct}
    except Exception as e:
        logging.error(f"Error calculating bond performance: {e}")
        return {'pnl': 0, 'pnl_pct': 0}
