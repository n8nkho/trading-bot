"""
Market Regime Center

Single source of truth for market regime and macro snapshot.
Lightweight and defensive: falls back gracefully if data is unavailable.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

import yfinance as yf

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "regime_center.log"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
REGIME_FILE = DATA_DIR / "market_regime.json"

RegimeName = Literal["RISK_ON", "NEUTRAL", "RISK_OFF", "CRASH"]


@dataclass
class RegimeSnapshot:
    regime: RegimeName
    vix: Optional[float]
    spy_trend: Optional[str]
    spy_50_above_200: Optional[bool]
    timestamp: str


def _safe_get_vix() -> Optional[float]:
    try:
        data = yf.Ticker("^VIX").history(period="2d")
        if len(data) == 0:
            return None
        return float(data["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"Failed to fetch VIX: {type(e).__name__}: {e}")
        return None


def _safe_get_spy_trend() -> tuple[Optional[str], Optional[bool]]:
    try:
        data = yf.Ticker("SPY").history(period="220d")
        if len(data) < 200:
            return None, None
        close = data["Close"]
        spy_current = float(close.iloc[-1])
        spy_50 = float(close.rolling(window=50).mean().iloc[-1])
        spy_200 = float(close.rolling(window=200).mean().iloc[-1])
        if spy_current > spy_200 and spy_50 > spy_200:
            trend = "UP"
        elif spy_current < spy_200 and spy_50 < spy_200:
            trend = "DOWN"
        else:
            trend = "SIDEWAYS"
        above = spy_50 > spy_200
        return trend, above
    except Exception as e:
        logger.warning(f"Failed to fetch SPY trend: {type(e).__name__}: {e}")
        return None, None


def _classify_regime(vix: Optional[float], trend: Optional[str]) -> RegimeName:
    # Conservative defaults if we don't know
    if vix is None or trend is None:
        return "NEUTRAL"

    if vix >= 35:
        return "CRASH"
    if vix >= 25 or trend == "DOWN":
        return "RISK_OFF"
    if vix <= 15 and trend == "UP":
        return "RISK_ON"
    return "NEUTRAL"


def compute_regime() -> RegimeSnapshot:
    """Compute a fresh regime snapshot from market data."""
    vix = _safe_get_vix()
    trend, above = _safe_get_spy_trend()
    regime = _classify_regime(vix, trend)
    snap = RegimeSnapshot(
        regime=regime,
        vix=vix,
        spy_trend=trend,
        spy_50_above_200=above,
        timestamp=datetime.utcnow().isoformat(),
    )
    try:
        with open(REGIME_FILE, "w") as f:
            json.dump(asdict(snap), f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to persist regime snapshot: {type(e).__name__}: {e}")
    return snap


def get_current_regime(max_age_minutes: int = 15) -> dict:
    """
    Get current regime snapshot, computing a new one if missing or stale.

    Returns a dict to keep call-sites simple.
    """
    try:
        if REGIME_FILE.exists():
            with open(REGIME_FILE) as f:
                data = json.load(f)
            ts = data.get("timestamp")
            if ts:
                try:
                    t = datetime.fromisoformat(ts)
                    if datetime.utcnow() - t <= timedelta(minutes=max_age_minutes):
                        return data
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Failed to read {REGIME_FILE}: {type(e).__name__}: {e}")

    snap = compute_regime()
    return asdict(snap)


if __name__ == "__main__":
    snap = compute_regime()
    print(json.dumps(asdict(snap), indent=2))

