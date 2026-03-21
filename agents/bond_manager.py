import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import os
from dotenv import load_dotenv
import logging

# Instrument/ticker config (no hard-coded ticker literals).
from utils.market_assets import require_market_assets

# Constants
RISK_ON_BOND_PCT = 0.15
RISK_OFF_BOND_PCT = 0.40

# Load environment variables
load_dotenv()
api_key = os.getenv("APCA_API_KEY_ID")
secret_key = os.getenv("APCA_API_SECRET_KEY")

def _get_client():
    """
    Lazy Alpaca client creation.
    This prevents import-time crashes when credentials are not present.
    """
    try:
        if not api_key or not secret_key:
            return None
        return TradingClient(api_key, secret_key, paper=True)
    except Exception:
        return None

def get_market_regime():
    assets = require_market_assets()
    vix_symbol = assets.get("vix_symbol")
    equity_symbol = (assets.get("vix_insurance") or {}).get("underlying_symbol")
    if not vix_symbol or not equity_symbol:
        return "NEUTRAL"

    vix_data = yf.Ticker(vix_symbol).history(period="1d")
    current_vix = vix_data['Close'].iloc[-1]
    equity_data = yf.Ticker(equity_symbol).history(period="200d")
    equity_50ma = equity_data['Close'].rolling(window=50).mean().iloc[-1]
    equity_200ma = equity_data['Close'].rolling(window=200).mean().iloc[-1]
    equity_current = equity_data['Close'].iloc[-1]

    if current_vix < 15 and equity_current > equity_200ma:
        return "RISK_ON"
    elif current_vix > 25 or equity_current < equity_200ma:
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
        client = _get_client()
        if client is None:
            return 0, 0

        assets = require_market_assets()
        bond_ticker = (assets.get("bond_manager") or {}).get("bond_ticker")
        if not bond_ticker:
            return 0, 0

        position = client.get_open_position(bond_ticker)
        return position.qty, position.market_value
    except Exception:
        return 0, 0

def rebalance_bonds(portfolio_value):
    market_regime = get_market_regime()
    assets = require_market_assets()
    bond_ticker = (assets.get("bond_manager") or {}).get("bond_ticker")
    if not bond_ticker:
        logging.warning("Bond strategy disabled: missing bond_ticker in config/market_assets.json")
        return []

    target_allocation = calculate_bond_target(portfolio_value, market_regime)
    current_qty, current_value = get_current_bond_position()
    diff = target_allocation - current_value

    orders = []
    if diff > 0:
        orders.append({'action': 'buy', 'qty': diff / 100, 'ticker': bond_ticker})
    elif diff < 0:
        orders.append({'action': 'sell', 'qty': -diff / 100, 'ticker': bond_ticker})

    logging.info(f"Rebalancing bonds: {orders}")
    return orders

def bonds_performance():
    try:
        client = _get_client()
        if client is None:
            return {'pnl': 0, 'pnl_pct': 0}

        assets = require_market_assets()
        bond_ticker = (assets.get("bond_manager") or {}).get("bond_ticker")
        if not bond_ticker:
            return {'pnl': 0, 'pnl_pct': 0}

        position = client.get_open_position(bond_ticker)
        entry_price = position.avg_entry_price
        current_price = yf.Ticker(bond_ticker).history(period="1d")['Close'].iloc[-1]
        pnl = (current_price - entry_price) * position.qty
        pnl_pct = (pnl / (entry_price * position.qty)) * 100
        return {'pnl': pnl, 'pnl_pct': pnl_pct}
    except Exception as e:
        logging.error(f"Error calculating bond performance: {e}")
        return {'pnl': 0, 'pnl_pct': 0}
