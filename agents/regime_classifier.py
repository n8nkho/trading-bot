"""
Market Regime Classifier
Classifies current market into one of 6 regimes and returns
the active strategy set for that regime.
"""
import logging
import yfinance as yf
import numpy as np
from datetime import datetime
from pathlib import Path
import json

logger = logging.getLogger(__name__)
DATA_DIR = Path("data")
REGIME_STATE_FILE = DATA_DIR / "regime_state.json"

REGIMES = {
    "BULL_TREND":  ["screener", "pead", "low_bounce", "squeeze", "etf_rebalance", "lag_detector", "vol_compression"],
    "BEAR_TREND":  ["bear_playbook", "vix_spike", "vol_compression"],
    "HIGH_VOL":    ["vix_spike", "bear_playbook"],
    "LOW_VOL":     ["vol_compression", "screener", "low_bounce"],
    "CHOPPY":      ["vol_compression", "low_bounce"],
    "CRISIS":      ["bear_playbook"],
}

def get_adx(prices, period=14):
    """Calculate Average Directional Index (trend strength)."""
    try:
        high = prices["High"]
        low = prices["Low"]
        close = prices["Close"]
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        tr = np.maximum(
            (high - low).values,
            np.maximum(
                (high - close.shift(1)).abs().values,
                (low - close.shift(1)).abs().values
            )
        )
        import pandas as pd
        tr_series = pd.Series(tr, index=close.index)
        atr = tr_series.ewm(span=period, min_periods=period).mean()
        plus_di = 100 * (plus_dm.ewm(span=period, min_periods=period).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(span=period, min_periods=period).mean() / atr)
        denom = (plus_di + minus_di).replace(0, 1)
        dx = 100 * (plus_di - minus_di).abs() / denom
        adx = dx.ewm(span=period, min_periods=period).mean()
        return float(adx.iloc[-1])
    except Exception as e:
        logger.warning(f"ADX calculation failed: {e}")
        return 20.0


def classify_regime():
    """
    Classify current market regime.
    Returns dict with regime name, active strategies, metrics, timestamp.
    """
    try:
        spy = yf.Ticker("SPY").history(period="30d")
        vix_data = yf.Ticker("^VIX").history(period="5d")
        hyg = yf.Ticker("HYG").history(period="5d")
        lqd = yf.Ticker("LQD").history(period="5d")

        vix = float(vix_data["Close"].iloc[-1]) if not vix_data.empty else 20.0
        vix_prev = float(vix_data["Close"].iloc[-2]) if len(vix_data) >= 2 else vix
        vix_1d_change = (vix - vix_prev) / max(vix_prev, 0.01)

        spy_5d_return = 0.0
        if len(spy) >= 6:
            spy_5d_return = (float(spy["Close"].iloc[-1]) - float(spy["Close"].iloc[-6])) / float(spy["Close"].iloc[-6])

        adx = get_adx(spy) if len(spy) >= 20 else 20.0

        credit_stress = False
        if not hyg.empty and not lqd.empty and len(hyg) >= 2 and len(lqd) >= 2:
            hyg_ret = (float(hyg["Close"].iloc[-1]) - float(hyg["Close"].iloc[0])) / max(float(hyg["Close"].iloc[0]), 0.01)
            lqd_ret = (float(lqd["Close"].iloc[-1]) - float(lqd["Close"].iloc[0])) / max(float(lqd["Close"].iloc[0]), 0.01)
            credit_stress = (lqd_ret - hyg_ret) > 0.02

        if vix > 35 or (vix > 28 and credit_stress):
            regime = "CRISIS"
        elif vix > 25 and spy_5d_return < -0.03:
            regime = "BEAR_TREND"
        elif vix > 22 and vix_1d_change > 0.15:
            regime = "HIGH_VOL"
        elif vix < 15 and adx < 15:
            regime = "LOW_VOL"
        elif adx < 18 and abs(spy_5d_return) < 0.01:
            regime = "CHOPPY"
        else:
            regime = "BULL_TREND"

        result = {
            "regime": regime,
            "active_strategies": REGIMES[regime],
            "metrics": {
                "vix": vix,
                "vix_1d_change": vix_1d_change,
                "spy_5d_return": spy_5d_return,
                "adx": adx,
                "credit_stress": credit_stress,
            },
            "timestamp": datetime.now().isoformat()
        }

        DATA_DIR.mkdir(exist_ok=True)
        with open(REGIME_STATE_FILE, "w") as f:
            json.dump(result, f, indent=2)

        logger.info(f"Regime: {regime} | VIX={vix:.1f} | SPY 5d={spy_5d_return:.1%} | ADX={adx:.1f}")
        return result

    except Exception as e:
        logger.error(f"Regime classification failed: {e}")
        fallback = {
            "regime": "BULL_TREND",
            "active_strategies": REGIMES["BULL_TREND"],
            "metrics": {},
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }
        return fallback


def load_last_regime():
    """Load last saved regime (avoids redundant API calls)."""
    try:
        if REGIME_STATE_FILE.exists():
            with open(REGIME_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"regime": "BULL_TREND", "active_strategies": REGIMES["BULL_TREND"], "metrics": {}}


def strategy_is_active(strategy_name, regime_data=None):
    """Check if a given strategy is active in the current regime."""
    if regime_data is None:
        regime_data = load_last_regime()
    return strategy_name in regime_data.get("active_strategies", REGIMES["BULL_TREND"])
