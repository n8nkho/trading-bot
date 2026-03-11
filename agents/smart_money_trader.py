from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from agents.regime_center import get_current_regime

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    filename=log_dir / "smart_money.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "META", "GOOGL", "SPY", "QQQ"]
BASE_POSITION_PCT = 0.05
MAX_POSITION_PCT = 0.10


def _safe_download(ticker: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            logger.warning(f"{ticker}: No data for {period}/{interval}")
            return None
        return df
    except Exception as e:
        logger.error(f"{ticker}: Error downloading data ({period}, {interval}): {e}")
        return None


def detect_order_blocks(ticker: str, days: int = 60) -> List[float]:
    logger.info(f"Detecting order blocks for {ticker} over the last {days} days.")
    df = _safe_download(ticker, period=f"{days}d", interval="1h")
    if df is None or len(df) < 10:
        return []

    levels: List[float] = []
    # Handle possible MultiIndex columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        high_series = df["High"].iloc[:, 0]
        low_series = df["Low"].iloc[:, 0]
        close_series = df["Close"].iloc[:, 0]
    else:
        high_series = df["High"]
        low_series = df["Low"]
        close_series = df["Close"]

    for i in range(len(df) - 6):
        window_high = high_series.iloc[i : i + 3]
        window_low = low_series.iloc[i : i + 3]
        window_close = close_series.iloc[i : i + 3]
        high_max = float(window_high.max())
        low_min = float(window_low.min())
        if low_min <= 0:
            continue
        range_pct = (high_max - low_min) / low_min
        if float(range_pct) < 0.02:
            fwd = close_series.iloc[i + 3 : i + 7]
            if fwd.empty:
                continue
            close_max = float(fwd.max())
            last_close = float(window_close.iloc[-1])
            if last_close <= 0:
                continue
            move_pct = (close_max - last_close) / last_close
            if float(move_pct) > 0.05:
                levels.append(last_close)
    return levels


def find_liquidity_sweep(ticker: str) -> bool:
    logger.info(f"Finding liquidity sweep for {ticker}.")
    df = _safe_download(ticker, period="10d", interval="1h")
    if df is None or len(df) < 5:
        return False

    if isinstance(df.columns, pd.MultiIndex):
        low_series = df["Low"].iloc[:, 0]
        open_series = df["Open"].iloc[:, 0]
        close_series = df["Close"].iloc[:, 0]
    else:
        low_series = df["Low"]
        open_series = df["Open"]
        close_series = df["Close"]

    recent_low = float(low_series.min())
    for i in range(len(df) - 1):
        low_i = float(low_series.iloc[i])
        if low_i <= 0:
            continue
        if low_i <= recent_low * 0.999:
            next_open = float(open_series.iloc[i + 1])
            next_close = float(close_series.iloc[i + 1])
            if next_close > next_open:
                return True
    return False


def check_structure_break(ticker: str) -> Optional[str]:
    logger.info(f"Checking structure break for {ticker}.")
    df = _safe_download(ticker, period="30d", interval="1h")
    if df is None or len(df) < 3:
        return None
    # Ensure 1D arrays for consistent indexing (yfinance can return Series or 2D)
    if isinstance(df.columns, pd.MultiIndex):
        high_ser = df["High"].iloc[:, 0]
        low_ser = df["Low"].iloc[:, 0]
    else:
        high_ser = df["High"]
        low_ser = df["Low"]
    highs = np.asarray(high_ser).ravel()
    lows = np.asarray(low_ser).ravel()
    if len(highs) < 2 or len(lows) < 2:
        return None
    h1, h2 = float(highs[-2]), float(highs[-1])
    l1, l2 = float(lows[-2]), float(lows[-1])
    if h2 < h1 and l2 > l1:
        return "BULLISH_BREAK"
    if h2 > h1 and l2 < l1:
        return "BEARISH_BREAK"
    return None


def smart_money_entry(ticker: str) -> Dict:
    logger.info(f"Evaluating smart money entry for {ticker}.")
    order_blocks = detect_order_blocks(ticker)
    liquidity_sweep = find_liquidity_sweep(ticker)
    structure_break = check_structure_break(ticker)

    if not order_blocks:
        return {"ticker": ticker, "action": "HOLD", "confidence": 0.0, "reason": "No order blocks"}
    if not liquidity_sweep or not structure_break:
        return {
            "ticker": ticker,
            "action": "HOLD",
            "confidence": 0.0,
            "reason": f"No aligned sweep/structure (sweep={liquidity_sweep}, structure={structure_break})",
        }

    if structure_break == "BULLISH_BREAK":
        action = "BUY"
        confidence = 0.8
    else:
        action = "SELL"
        confidence = 0.7

    reason = f"{structure_break} with sweep and {len(order_blocks)} order blocks"
    logger.info(f"{ticker}: Smart money signal {action} (conf={confidence:.2f}) - {reason}")
    return {
        "ticker": ticker,
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "order_blocks": order_blocks,
        "structure_break": structure_break,
        "liquidity_sweep": liquidity_sweep,
    }


def smart_money_strategy(portfolio_value: float) -> List[Dict]:
    logger.info("Running smart money strategy.")
    regime_snapshot = get_current_regime()
    regime_name = (regime_snapshot.get("regime") or "NEUTRAL").upper()

    if regime_name == "CRASH":
        size_mult = 0.25
    elif regime_name == "RISK_OFF":
        size_mult = 0.5
    elif regime_name == "RISK_ON":
        size_mult = 1.25
    else:
        size_mult = 1.0

    base_dollars = portfolio_value * BASE_POSITION_PCT * size_mult
    max_dollars = portfolio_value * MAX_POSITION_PCT * size_mult

    recs: List[Dict] = []
    for ticker in WATCHLIST:
        entry = smart_money_entry(ticker)
        if entry.get("action") not in {"BUY", "SELL"}:
            continue
        size = min(max_dollars, base_dollars)
        rec = {
            "ticker": ticker,
            "action": entry["action"],
            "confidence": entry["confidence"],
            "reason": entry["reason"],
            "position_size": round(size, 2),
            "regime": regime_name,
            "strategy_id": "smart_money",
            "timestamp": datetime.utcnow().isoformat(),
        }
        recs.append(rec)
        logger.info(
            f"SMART_MONEY: {ticker} {rec['action']} size=${rec['position_size']:.2f} "
            f"(regime={regime_name}, conf={rec['confidence']:.2f})"
        )

    logger.info(f"Smart money produced {len(recs)} recommendations for regime={regime_name}")
    return recs


if __name__ == "__main__":
    signals = smart_money_strategy(100000)
    print(f"Smart money signals ({len(signals)}):")
    for s in signals:
        print(s)
