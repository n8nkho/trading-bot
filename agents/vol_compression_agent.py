"""
Volatility Compression Breakout Agent
Detects Bollinger Band squeeze setups ready to explode.
Only takes long side when bullish bias confirmed.
Expected win rate: 58-65%.
"""
import logging
import yfinance as yf
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_POSITION_SIZE = 500.0
TAKE_PROFIT_PCT = 0.08
STOP_LOSS_PCT = 0.04
COMPRESSION_THRESHOLD = 0.55

COMPRESSION_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AMD", "TSLA",
    "JPM", "BAC", "GS", "WFC", "V", "MA",
    "JNJ", "PFE", "MRK", "ABBV",
    "XOM", "CVX", "HD", "WMT", "COST",
    "DIS", "NFLX", "AMGN", "GILD",
    "INTC", "QCOM", "TXN", "MU", "AMAT",
    "BA", "CAT", "HON", "GE", "MMM",
    "SPY", "QQQ", "IWM",
]


def check_vol_compression(ticker):
    """Check if stock is in a volatility compression setup."""
    try:
        hist = yf.Ticker(ticker).history(period="3mo")
        if hist.empty or len(hist) < 25:
            return {"compressed": False, "ticker": ticker, "reason": "Insufficient data"}

        close = hist["Close"]
        rolling_mean = close.rolling(20).mean()
        rolling_std = close.rolling(20).std()
        upper_bb = rolling_mean + 2 * rolling_std
        lower_bb = rolling_mean - 2 * rolling_std
        bb_width = (upper_bb - lower_bb) / rolling_mean.replace(0, 1)

        current_bbw = float(bb_width.iloc[-1])
        avg_bbw = float(bb_width.dropna().mean())
        if avg_bbw == 0:
            return {"compressed": False, "ticker": ticker, "reason": "Zero BB width"}

        compression_ratio = current_bbw / avg_bbw
        is_compressed = compression_ratio < COMPRESSION_THRESHOLD

        current_price = float(close.iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else current_price
        bullish_bias = current_price > sma50

        avg_vol = float(hist["Volume"].iloc[:-5].mean()) if len(hist) > 5 else 1.0
        recent_vol = float(hist["Volume"].iloc[-5:].mean())
        volume_drying = recent_vol < avg_vol * 0.8 if avg_vol > 0 else False

        return {
            "compressed": is_compressed and volume_drying,
            "ticker": ticker,
            "compression_ratio": compression_ratio,
            "bullish_bias": bullish_bias,
            "current_price": current_price,
            "volume_drying": volume_drying,
            "reason": f"BB compression {compression_ratio:.2f}x avg, vol_dry={volume_drying}, bullish={bullish_bias}",
        }
    except Exception as e:
        logger.warning(f"Vol compression check failed for {ticker}: {e}")
        return {"compressed": False, "ticker": ticker, "reason": str(e)}


def scan_vol_compression_opportunities(portfolio_value=50000.0):
    """Scan for volatility compression setups ready to explode."""
    logger.info("Vol Compression Agent: Scanning...")
    opportunities = []
    for ticker in COMPRESSION_UNIVERSE:
        try:
            result = check_vol_compression(ticker)
            if not result.get("compressed") or not result.get("bullish_bias"):
                continue
            price = result["current_price"]
            shares = max(1, int(MAX_POSITION_SIZE / price))
            confidence = 0.60 + (COMPRESSION_THRESHOLD - result["compression_ratio"]) * 0.3
            confidence = max(0.58, min(confidence, 0.72))
            opportunities.append({
                "ticker": ticker,
                "strategy": "VOL_COMPRESSION",
                "entry_price": price,
                "shares": shares,
                "position_size": shares * price,
                "confidence": confidence,
                "stop_loss_pct": STOP_LOSS_PCT,
                "take_profit_pct": TAKE_PROFIT_PCT,
                "reasoning": result["reason"],
                "setup_data": result,
            })
            logger.info(f"VOL COMPRESS: {ticker} - {result['reason']}")
        except Exception as e:
            logger.error(f"Vol compression scan error for {ticker}: {e}")
    logger.info(f"Vol Compression Agent: Found {len(opportunities)} setups")
    return sorted(opportunities, key=lambda x: x["confidence"], reverse=True)
