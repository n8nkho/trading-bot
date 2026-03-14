"""
Forex Sniper Agent (EXPERIMENTAL / OPTIONAL).

Requires OANDA_API_KEY and OANDA_ACCOUNT_ID in environment. If not set,
all entry points no-op and return None/empty. No trading is attempted.
"""

from __future__ import annotations

import datetime
import logging
import os
import pytz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

OANDA_API_KEY = os.getenv("OANDA_API_KEY") or ""
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID") or ""
_OANDA_ENABLED = bool(OANDA_API_KEY and OANDA_ACCOUNT_ID and "YOUR_" not in OANDA_API_KEY)

# Lazy init to avoid import errors when OANDA not configured
_api = None

def _get_api():
    global _api
    if not _OANDA_ENABLED:
        return None
    if _api is None:
        try:
            from oandapyV20 import API
            _api = API(access_token=OANDA_API_KEY)
        except Exception as e:
            logger.warning("Forex sniper: OANDA API init failed: %s", e)
            return None
    return _api

MAX_RISK_PCT = 0.005
STOP_LOSS_PIPS = 10
TARGET_1_PIPS = 10
TARGET_2_PIPS = 20
TARGET_3_PIPS = 30
MAX_TRADES_PER_DAY = 3
MAX_CONSECUTIVE_LOSSES = 2
MAX_HOLD_HOURS = 4
TRADING_PAIR = "EUR_USD"
TIME_WINDOW_START = 8
TIME_WINDOW_END = 12


def is_trading_window() -> bool:
    """True if within 8 AM - 12 PM EST weekdays."""
    est = pytz.timezone("US/Eastern")
    now = datetime.datetime.now(est)
    if now.weekday() >= 5:
        return False
    return TIME_WINDOW_START <= now.hour < TIME_WINDOW_END


def get_eurusd_data(period: str = "1d", interval: str = "15m"):
    """Fetch EUR/USD from yfinance (no OANDA required)."""
    try:
        import pandas as pd
        import yfinance as yf
        data = yf.download("EURUSD=X", period=period, interval=interval, progress=False, group_by="ticker")
        if data.empty:
            return __import__("pandas").DataFrame()
        if isinstance(data.columns, __import__("pandas").MultiIndex):
            data = data["EURUSD=X"] if "EURUSD=X" in data.columns.get_level_values(0) else data
        return data
    except Exception as e:
        logger.error("Forex sniper: get_eurusd_data failed: %s", e)
        return __import__("pandas").DataFrame()


def find_sniper_setup():
    """
    Identify a valid EUR/USD setup. Returns None if OANDA not configured or no setup.
    """
    if not _OANDA_ENABLED:
        logger.debug("Forex sniper: disabled (no OANDA_API_KEY / OANDA_ACCOUNT_ID)")
        return None
    if not is_trading_window():
        return None
    api = _get_api()
    if api is None:
        return None
    try:
        data = get_eurusd_data()
        if data is None or (hasattr(data, "empty") and data.empty) or len(data) < 20:
            return None
        import pandas as pd
        close = data["Close"] if "Close" in data.columns else data.iloc[:, 0]
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))
        rsi_val = float(rsi.iloc[-1]) if len(rsi) else 50.0
        current_price = float(close.iloc[-1])
        low_20 = close.rolling(20).min().iloc[-1]
        high_20 = close.rolling(20).max().iloc[-1]
        if rsi_val < 35 and current_price <= low_20 * 1.001:
            return {
                "signal": "BUY",
                "entry_price": current_price,
                "stop_loss": current_price - 0.001,
                "take_profit_1": current_price + 0.001,
                "reason": f"RSI {rsi_val:.1f} oversold near support",
            }
        if rsi_val > 65 and current_price >= high_20 * 0.999:
            return {
                "signal": "SELL",
                "entry_price": current_price,
                "stop_loss": current_price + 0.001,
                "take_profit_1": current_price - 0.001,
                "reason": f"RSI {rsi_val:.1f} overbought near resistance",
            }
    except Exception as e:
        logger.warning("Forex sniper: find_sniper_setup failed: %s", e)
    return None


def monitor_open_trades():
    """No-op when OANDA not configured."""
    if not _OANDA_ENABLED:
        return
    # Placeholder: would list/update OANDA positions
    pass


def check_daily_limits() -> bool:
    """True if still under daily limits (placeholder)."""
    return True
