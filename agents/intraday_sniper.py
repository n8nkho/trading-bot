"""
Intraday Sniper Agent - Fast scalping for quick profits
Targets 10-20 quick trades per day with tight stops and targets
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time
import pytz
import logging
import json
import os
from pathlib import Path

# Setup logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "sniper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
MAX_INTRADAY_POSITIONS = 3
POSITION_SIZE = 500  # $500 per position
STOP_LOSS_PCT = -1.0  # -1% stop
TARGET1_PCT = 0.5     # +0.5% first target (sell 50%)
TARGET2_PCT = 1.0     # +1% second target (sell rest)
DROP_THRESHOLD = -2.0  # -2% drop in 5 min
VOLUME_SPIKE = 3.0     # 3x average volume
RSI_OVERSOLD = 30
MARKET_CLOSE_TIME = time(15, 55)  # Close all by 3:55 PM ET

# Data directory
data_dir = Path("data")
data_dir.mkdir(exist_ok=True)
TRADES_FILE = data_dir / "intraday_trades.jsonl"


def calculate_rsi(prices, period=5):
    """Calculate RSI for intraday (5-period for 1-min bars)"""
    if len(prices) < period + 1:
        return 50  # Neutral if not enough data
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def get_intraday_data(ticker, period='1d', interval='1m'):
    """Fetch 1-minute intraday data"""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)
        
        if df.empty:
            logger.warning(f"No intraday data for {ticker}")
            return None
        
        return df
    except Exception as e:
        logger.error(f"Error fetching intraday data for {ticker}: {e}")
        return None


def detect_sudden_move(df):
    """Detect sudden price drops with volume spikes in last 5 minutes"""
    if df is None or len(df) < 15:
        return None
    
    # Last 5 minutes (5 bars)
    recent = df.tail(5)
    # Previous 10 minutes for comparison
    baseline = df.tail(15).head(10)
    
    if len(recent) < 5 or len(baseline) < 5:
        return None
    
    # Calculate metrics
    price_change_pct = ((recent['Close'].iloc[-1] - recent['Close'].iloc[0]) / recent['Close'].iloc[0]) * 100
    avg_volume_baseline = baseline['Volume'].mean()
    recent_volume = recent['Volume'].mean()
    volume_ratio = recent_volume / avg_volume_baseline if avg_volume_baseline > 0 else 0
    
    current_price = recent['Close'].iloc[-1]
    prices = df['Close'].values
    rsi = calculate_rsi(prices, period=5)
    
    # Day's low and high
    day_low = df['Low'].min()
    day_high = df['High'].max()
    
    metrics = {
        'current_price': current_price,
        'price_change_5min': price_change_pct,
        'volume_ratio': volume_ratio,
        'rsi_5min': rsi,
        'day_low': day_low,
        'day_high': day_high,
        'stabilizing': current_price > day_low * 1.01  # Above low by 1%
    }
    
    # Check if it's a sudden drop opportunity
    is_opportunity = (
        price_change_pct < DROP_THRESHOLD and
        volume_ratio > VOLUME_SPIKE and
        rsi < RSI_OVERSOLD
    )
    
    return metrics if is_opportunity else None


def scan_intraday_opportunities(portfolio_value=10000):
    """Scan for intraday scalping opportunities"""
    logger.info("Starting intraday opportunity scan...")
    
    # Load watchlist
    watchlist_file = Path("config/watchlist.json")
    if not watchlist_file.exists():
        logger.error("Watchlist file not found")
        return []
    
    with open(watchlist_file, 'r') as f:
        watchlist_data = json.load(f)
        watchlist = watchlist_data.get('tickers', [])
    
    opportunities = []
    
    for ticker in watchlist:
        logger.info(f"Scanning {ticker}...")
        
        # Get 1-minute data
        df = get_intraday_data(ticker, period='1d', interval='1m')
        
        if df is None:
            continue
        
        # Detect sudden moves
        metrics = detect_sudden_move(df)
        
        if metrics:
            opportunity = {
                'ticker': ticker,
                'timestamp': datetime.now().isoformat(),
                'entry_price': metrics['current_price'],
                'metrics': metrics
            }
            opportunities.append(opportunity)
            logger.info(f"✅ Opportunity found: {ticker} at ${metrics['current_price']:.2f}")
            logger.info(f"   Drop: {metrics['price_change_5min']:.2f}%, "
                       f"Volume: {metrics['volume_ratio']:.1f}x, "
                       f"RSI: {metrics['rsi_5min']:.1f}")
    
    logger.info(f"Found {len(opportunities)} intraday opportunities")
    return opportunities


def evaluate_quick_entry(ticker, current_price, metrics):
    """Fast entry decision without AI - pure technical rules"""
    
    # Check technical conditions
    rsi_ok = metrics['rsi_5min'] < RSI_OVERSOLD
    volume_ok = metrics['volume_ratio'] > VOLUME_SPIKE
    drop_ok = metrics['price_change_5min'] < DROP_THRESHOLD
    stabilizing = metrics['stabilizing']
    
    if not (rsi_ok and volume_ok and drop_ok and stabilizing):
        reason = "Technical conditions not met: "
        if not rsi_ok:
            reason += f"RSI={metrics['rsi_5min']:.1f} "
        if not volume_ok:
            reason += f"Vol={metrics['volume_ratio']:.1f}x "
        if not drop_ok:
            reason += f"Drop={metrics['price_change_5min']:.1f}% "
        if not stabilizing:
            reason += "Not stabilizing "
        
        return {
            'action': 'SKIP',
            'ticker': ticker,
            'reason': reason.strip(),
            'timestamp': datetime.now().isoformat()
        }
    
    # Calculate position size (min of $500 or 2% of portfolio)
    max_position = min(POSITION_SIZE, portfolio_value * 0.02)
    shares = int(max_position / current_price)
    
    if shares < 1:
        return {
            'action': 'SKIP',
            'ticker': ticker,
            'reason': f'Position too small: ${max_position:.2f} / ${current_price:.2f}',
            'timestamp': datetime.now().isoformat()
        }
    
    # Calculate stop and targets
    stop_price = current_price * (1 + STOP_LOSS_PCT / 100)
    target1_price = current_price * (1 + TARGET1_PCT / 100)
    target2_price = current_price * (1 + TARGET2_PCT / 100)
    
    decision = {
        'action': 'BUY',
        'ticker': ticker,
        'entry_price': current_price,
        'shares': shares,
        'position_value': shares * current_price,
        'stop_loss': stop_price,
        'target1': target1_price,
        'target2': target2_price,
        'reason': (f"Oversold bounce setup: RSI={metrics['rsi_5min']:.1f}, "
                  f"Drop={metrics['price_change_5min']:.1f}%, "
                  f"Volume={metrics['volume_ratio']:.1f}x"),
        'metrics': metrics,
        'timestamp': datetime.now().isoformat()
    }
    
    logger.info(f"🎯 BUY SIGNAL: {ticker} @ ${current_price:.2f}")
    logger.info(f"   Shares: {shares}, Stop: ${stop_price:.2f}, "
               f"T1: ${target1_price:.2f}, T2: ${target2_price:.2f}")
    
    return decision


def rapid_exit_check(positions):
    """Check positions every 30 seconds for exit conditions"""
    logger.info(f"Checking {len(positions)} intraday positions for exits...")
    
    exit_orders = []
    et_tz = pytz.timezone('US/Eastern')
    current_time_et = datetime.now(et_tz).time()
    
    # Force close all positions near market close
    force_close = current_time_et >= MARKET_CLOSE_TIME
    
    for position in positions:
        ticker = position['ticker']
        entry_price = position['entry_price']
        shares = position['shares']
        stop_loss = position['stop_loss']
        target1 = position['target1']
        target2 = position['target2']
        shares_remaining = position.get('shares_remaining', shares)
        hit_target1 = position.get('hit_target1', False)
        
        # Get current price
        try:
            stock = yf.Ticker(ticker)
            current_price = stock.info.get('currentPrice') or stock.info.get('regularMarketPrice')
            
            if not current_price:
                # Try getting from recent data
                df = get_intraday_data(ticker, period='1d', interval='1m')
                if df is not None and not df.empty:
                    current_price = df['Close'].iloc[-1]
                else:
                    logger.warning(f"Could not get current price for {ticker}")
                    continue
        except Exception as e:
            logger.error(f"Error getting price for {ticker}: {e}")
            continue
        
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Exit logic
        exit_reason = None
        sell_qty = 0
        
        if force_close:
            exit_reason = "Market closing - force exit all positions"
            sell_qty = shares_remaining
        elif current_price <= stop_loss:
            exit_reason = f"Stop loss hit: ${current_price:.2f} <= ${stop_loss:.2f}"
            sell_qty = shares_remaining
        elif not hit_target1 and current_price >= target1:
            exit_reason = f"Target 1 hit: ${current_price:.2f} >= ${target1:.2f} - Sell 50%"
            sell_qty = shares_remaining // 2
            position['hit_target1'] = True
        elif hit_target1 and current_price >= target2:
            exit_reason = f"Target 2 hit: ${current_price:.2f} >= ${target2:.2f} - Sell remaining"
            sell_qty = shares_remaining
        
        if exit_reason and sell_qty > 0:
            exit_order = {
                'ticker': ticker,
                'action': 'SELL',
                'shares': sell_qty,
                'current_price': current_price,
                'entry_price': entry_price,
                'pnl_pct': pnl_pct,
                'reason': exit_reason,
                'timestamp': datetime.now().isoformat()
            }
            exit_orders.append(exit_order)
            
            # Update shares remaining
            position['shares_remaining'] = shares_remaining - sell_qty
            
            logger.info(f"🚨 EXIT SIGNAL: {ticker} - {exit_reason}")
            logger.info(f"   Sell {sell_qty} shares @ ${current_price:.2f}, P&L: {pnl_pct:+.2f}%")
            
            # Log trade to file
            log_trade(position, exit_order)
        else:
            logger.info(f"   {ticker}: ${current_price:.2f} ({pnl_pct:+.2f}%) - HOLD")
    
    return exit_orders


def log_trade(position, exit_order):
    """Log completed trade to JSONL file"""
    trade_record = {
        'ticker': position['ticker'],
        'entry_time': position['timestamp'],
        'exit_time': exit_order['timestamp'],
        'entry_price': position['entry_price'],
        'exit_price': exit_order['current_price'],
        'shares': exit_order['shares'],
        'pnl_pct': exit_order['pnl_pct'],
        'pnl_dollars': (exit_order['current_price'] - position['entry_price']) * exit_order['shares'],
        'exit_reason': exit_order['reason'],
        'entry_metrics': position.get('metrics', {})
    }
    
    # Append to JSONL file
    with open(TRADES_FILE, 'a') as f:
        f.write(json.dumps(trade_record) + '\n')
    
    logger.info(f"💾 Trade logged to {TRADES_FILE}")


if __name__ == "__main__":
    # Test the sniper
    print("Testing Intraday Sniper...")
    opportunities = scan_intraday_opportunities(portfolio_value=10000)
    
    if opportunities:
        print(f"\n✅ Found {len(opportunities)} opportunities:")
        for opp in opportunities:
            print(f"\n{opp['ticker']} @ ${opp['entry_price']:.2f}")
            decision = evaluate_quick_entry(
                opp['ticker'],
                opp['entry_price'],
                opp['metrics']
            )
            print(f"Decision: {decision['action']} - {decision['reason']}")
    else:
        print("\n❌ No opportunities found")
