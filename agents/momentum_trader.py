import logging
import pandas as pd
from datetime import datetime, time
import yfinance as yf
import pandas as pd
from functools import lru_cache

# Configure logging
logging.basicConfig(filename='logs/momentum.log', level=logging.INFO)
logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def get_liquid_stocks():
    """
    Get a list of liquid stocks from S&P 500 and Russell 2000.
    Returns ~500-700 stocks with volume > 5M shares.
    Cached to avoid repeated API calls.
    """
    logger.info("Fetching liquid stocks from S&P 500 and Russell 2000...")
    liquid_stocks = []
    
    try:
        # Get S&P 500 tickers
        sp500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        sp500_table = pd.read_html(sp500_url)[0]
        sp500_tickers = sp500_table['Symbol'].tolist()
        logger.info(f"Found {len(sp500_tickers)} S&P 500 tickers")
        
        # Get Russell 2000 tickers (top 200 by market cap)
        # Note: Full Russell 2000 list requires paid data, using approximation
        russell_url = 'https://en.wikipedia.org/wiki/Russell_2000_Index'
        try:
            russell_tables = pd.read_html(russell_url)
            russell_tickers = []
            for table in russell_tables:
                if 'Ticker' in table.columns or 'Symbol' in table.columns:
                    col = 'Ticker' if 'Ticker' in table.columns else 'Symbol'
                    russell_tickers.extend(table[col].tolist())
            russell_tickers = russell_tickers[:200]  # Top 200
            logger.info(f"Found {len(russell_tickers)} Russell 2000 tickers")
        except Exception as e:
            logger.warning(f"Could not fetch Russell 2000: {e}")
            russell_tickers = []
        
        # Combine and deduplicate
        all_tickers = list(set(sp500_tickers + russell_tickers))
        logger.info(f"Total unique tickers: {len(all_tickers)}")
        
        # Filter by volume > 5M shares
        for ticker in all_tickers:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                avg_volume = info.get('averageVolume', 0)
                
                if avg_volume > 5_000_000:
                    liquid_stocks.append(ticker)
                    
            except Exception as e:
                logger.debug(f"Error checking {ticker}: {e}")
                continue
        
        logger.info(f"Filtered to {len(liquid_stocks)} liquid stocks (volume > 5M)")
        return liquid_stocks
        
    except Exception as e:
        logger.error(f"Error fetching liquid stocks: {e}")
        # Fallback to major liquid stocks
        fallback = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 
                   'AMD', 'COIN', 'HOOD', 'PLTR', 'SOFI', 'RIVN', 'LCID']
        logger.info(f"Using fallback list of {len(fallback)} stocks")
        return fallback


def get_sp500_tickers():
    """
    Return a list of the top 100 most liquid S&P 500 tickers.
    """
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'BRK.B',
        'UNH', 'XOM', 'JNJ', 'JPM', 'V', 'PG', 'MA', 'HD', 'CVX', 'MRK',
        'ABBV', 'KO', 'AVGO', 'PEP', 'COST', 'TMO', 'MCD', 'CSCO', 'ACN',
        'LLY', 'DHR', 'ABT', 'NKE', 'DIS', 'TXN', 'VZ', 'ADBE', 'WMT',
        'CRM', 'NFLX', 'ORCL', 'AMD', 'INTC', 'CMCSA', 'PFE', 'PM', 'BA',
        'QCOM', 'T', 'UNP', 'HON', 'IBM', 'GE', 'INTU', 'SBUX', 'CAT',
        'PLTR', 'COIN', 'HOOD', 'SOFI', 'RIVN', 'LCID', 'NIO'
    ]

def scan_for_breakouts(stock_list):
    """
    Scan stocks for 3-8% moves from today's open.
    
    Args:
        stock_list: List of ticker symbols to scan
        
    Returns:
        List of dicts with breakout info: 
        [{'ticker': 'PLTR', 'pct_move': 5.2, 'current': 25.30, 'open': 24.05}, ...]
    """
    logger.info(f"Scanning {len(stock_list)} stocks for 3-8% breakouts...")
    breakouts = []
    
    for ticker in stock_list:
        try:
            stock = yf.Ticker(ticker)
            # Get today's data
            hist = stock.history(period='1d', interval='1m')
            
            if hist.empty:
                continue
                
            open_price = hist['Open'].iloc[0]
            current_price = hist['Close'].iloc[-1]
            
            # Calculate percentage move
            pct_move = ((current_price - open_price) / open_price) * 100
            
            # Filter for 3-8% moves (both up and down)
            if 3 <= abs(pct_move) <= 8:
                breakout_info = {
                    'ticker': ticker,
                    'pct_move': pct_move,
                    'current': current_price,
                    'open': open_price,
                    'direction': 'up' if pct_move > 0 else 'down'
                }
                breakouts.append(breakout_info)
                logger.info(f"BREAKOUT: {ticker} {pct_move:+.2f}% (${open_price:.2f} -> ${current_price:.2f})")
                
        except Exception as e:
            logger.debug(f"Error scanning {ticker}: {e}")
            continue
    
    logger.info(f"Found {len(breakouts)} breakouts meeting 3-8% criteria")
    return breakouts

def evaluate_momentum_entry(breakout_info):
    """
    Evaluate if the breakout meets entry criteria.
    
    Args:
        breakout_info: Dict with ticker, pct_move, current, open, direction
        
    Returns:
        bool: True if meets entry criteria
    """
    ticker = breakout_info['ticker']
    
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='1d', interval='1m')
        
        if hist.empty:
            return False
        
        # Calculate volume multiplier
        current_volume = hist['Volume'].sum()
        info = stock.info
        avg_volume = info.get('averageVolume', 1)
        volume_multiplier = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Calculate RSI (simplified 14-period)
        closes = hist['Close']
        if len(closes) >= 14:
            delta = closes.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]
        else:
            current_rsi = 50  # Neutral if not enough data
        
        # Entry criteria: volume > 3x average and RSI between 60-75
        if volume_multiplier > 3 and 60 <= current_rsi <= 75:
            logger.info(f"{ticker} MEETS ENTRY: volume {volume_multiplier:.2f}x, RSI {current_rsi:.2f}")
            return True
        else:
            logger.info(f"{ticker} does not meet entry: volume {volume_multiplier:.2f}x, RSI {current_rsi:.2f}")
            return False
            
    except Exception as e:
        logger.error(f"Error evaluating {ticker}: {e}")
        return False

def execute_momentum_trade(breakout_info):
    """
    Execute a buy order for the breakout stock.
    
    Args:
        breakout_info: Dict with ticker, pct_move, current, open, direction
    """
    ticker = breakout_info['ticker']
    pct_move = breakout_info['pct_move']
    current = breakout_info['current']
    
    logger.info(f"EXECUTING BUY ORDER: {ticker} at ${current:.2f} ({pct_move:+.2f}% move)")
    # TODO: Integrate with actual broker API

def monitor_momentum_exits():
    """Monitor trades for exit conditions."""
    logging.info("Monitoring trades for exit conditions.")

def momentum_strategy():
    """
    Main function to execute the momentum trading strategy.
    
    Workflow:
    1. Get 500-700 liquid stocks (cached)
    2. Scan for 3-8% breakouts
    3. Evaluate entry criteria (volume, RSI)
    4. Execute trades on qualified breakouts
    5. Monitor exits
    
    Target: Find 5-20 breakouts per day from 500-1000 stocks
    """
    current_time = datetime.now().time()
    
    # Only scan during market hours (9:30 AM - 10:30 AM ET for morning breakouts)
    tickers = get_sp500_tickers()
    if time(9, 30) <= current_time <= time(10, 30):
        logger.info("=" * 60)
        logger.info("MOMENTUM STRATEGY: Starting morning breakout scan")
        logger.info("=" * 60)
        
        # Step 1: Get liquid stocks (cached, only fetches once)
        logger.info(f"Scanning universe of {len(tickers)} S&P 500 stocks")
        
        # Step 2: Scan for 3-8% breakouts
        breakouts = scan_for_breakouts(tickers)
        logger.info(f"Found {len(breakouts)} breakouts (3-8% moves)")
        
        # Step 3 & 4: Evaluate and execute trades
        executed_count = 0
        for breakout_info in breakouts:
            if evaluate_momentum_entry(breakout_info):
                execute_momentum_trade(breakout_info)
                executed_count += 1
        
        logger.info(f"Executed {executed_count} trades out of {len(breakouts)} breakouts")
        logger.info("=" * 60)
    
    # Step 5: Monitor exits (runs throughout the day)
    monitor_momentum_exits()

if __name__ == "__main__":
    momentum_strategy()
