import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import os
import json
import time
import logging
import traceback
from datetime import datetime
from pathlib import Path
import yfinance as yf
from utils.local_llm import analyze_stock_drop
from agents.vision_analyst import analyze_chart_patterns, pattern_to_signal
import pandas as pd

# Load current parameters
DATA_DIR = Path("data")
CURRENT_PARAMS_FILE = DATA_DIR / "current_params.json"

def load_screening_params():
    """Load current screening parameters (may have been auto-tuned)"""
    try:
        if CURRENT_PARAMS_FILE.exists():
            with open(CURRENT_PARAMS_FILE, 'r') as f:
                params = json.load(f)
                logging.info(f"Loaded tuned parameters: RSI<{params['rsi_threshold']}, Drop: {params['drop_min']}% to {params['drop_max']}%")
                return params
        else:
            # Default parameters
            return {
                'rsi_threshold': 40,
                'drop_min': -15,
                'drop_max': -5,
                'volume_ratio_min': 1.5
            }
    except Exception as e:
        logging.error(f"Error loading parameters, using defaults: {e}")
        return {
            'rsi_threshold': 40,
            'drop_min': -15,
            'drop_max': -5,
            'volume_ratio_min': 1.5
        }

logging.basicConfig(
    filename='logs/screener.log', 
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
        'PLTR', 'COIN', 'HOOD', 'SOFI', 'RIVN', 'LCID', 'NIO', 'BABA',
        'TSM', 'SHOP', 'SQ', 'PYPL', 'UBER', 'LYFT', 'SNAP', 'PINS',
        'TWLO', 'ZM', 'DOCU', 'CRWD', 'NET', 'DDOG', 'SNOW', 'MDB',
        'OKTA', 'ZS', 'PANW', 'FTNT', 'NOW', 'WDAY', 'TEAM', 'SPLK',
        'CCI', 'AMT', 'EQIX', 'DLR', 'PSA', 'SPG', 'O', 'WELL',
        'ARE', 'AVB', 'EQR', 'VTR', 'ESS', 'MAA', 'UDR', 'CPT'
    ]

def get_russell2000_top_tickers():
    """
    Return a list of top liquid Russell 2000 stocks.
    These are smaller cap stocks that can have bigger moves.
    """
    return [
        'SIRI', 'PLUG', 'FUBO', 'LAZR', 'OPEN', 'RKT', 'UWMC', 'CLOV',
        'WISH', 'BARK', 'BODY', 'SPCE', 'ASTR', 'RKLB', 'MNDY', 'FROG',
        'DKNG', 'PENN', 'CHWY', 'ETSY', 'W', 'CVNA', 'APRN', 'BYND',
        'TDOC', 'PTON', 'ROKU', 'SPOT', 'TTD', 'MELI', 'SE', 'BKNG',
        'ABNB', 'DASH', 'RBLX', 'U', 'PATH', 'BILL', 'SMAR', 'GTLB',
        'S', 'DOCN', 'FSLY', 'ESTC', 'CFLT', 'NCNO', 'BRZE', 'JAMF',
        'SUMO', 'FROG', 'BIGC', 'ASAN', 'ZI', 'PCOR', 'TENB', 'ALRM',
        'QLYS', 'VRNS', 'MIME', 'BLKB', 'APPF', 'PRGS', 'MITK', 'QTWO'
    ]

def get_all_liquid_stocks():
    """
    Get a comprehensive list of 500-1000 liquid stocks to scan.
    
    Combines:
    - S&P 500 stocks (large cap)
    - Russell 2000 top stocks (small/mid cap)
    - Filters for volume > 1M shares and price > $5
    
    Returns:
        List of ticker symbols
    """
    logging.info("Building dynamic stock universe...")
    
    # Start with S&P 500 and Russell 2000 top stocks
    all_tickers = list(set(get_sp500_tickers() + get_russell2000_top_tickers()))
    logging.info(f"Starting with {len(all_tickers)} tickers from S&P 500 + Russell 2000")
    
    # Filter for liquid stocks (volume > 1M, price > $5)
    liquid_stocks = []
    for ticker in all_tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Check volume and price criteria
            avg_volume = info.get('averageVolume', 0)
            current_price = info.get('currentPrice', info.get('regularMarketPrice', 0))
            
            if avg_volume > 1_000_000 and current_price > 5:
                liquid_stocks.append(ticker)
        except Exception as e:
            logging.debug(f"Skipping {ticker} during filtering: {e}")
            continue
    
    logging.info(f"Filtered to {len(liquid_stocks)} liquid stocks (volume > 1M, price > $5)")
    return liquid_stocks

def run_screener():
    # Load current parameters (may have been auto-tuned)
    params = load_screening_params()
    
    # Get dynamic list of 500-1000 liquid stocks instead of static watchlist
    logging.info("=" * 80)
    logging.info("DYNAMIC SCREENER: Building stock universe...")
    logging.info("=" * 80)
    
    all_tickers = get_all_liquid_stocks()
    watchlist = [{'ticker': t, 'sector': 'Various', 'name': t} for t in all_tickers]
    
    logging.info(f"Scanning {len(watchlist)} stocks for opportunities...")
    logging.info(f"Criteria: Drop {params['drop_min']}% to {params['drop_max']}%, RSI < {params['rsi_threshold']}, Volume > {params['volume_ratio_min']}x")
    logging.info("=" * 80)

    candidates = []
    scanned_count = 0
    for stock in watchlist:
        ticker = stock['ticker']
        scanned_count += 1
        
        # Log progress every 50 stocks
        if scanned_count % 50 == 0:
            logging.info(f"Progress: {scanned_count}/{len(watchlist)} stocks scanned, {len(candidates)} candidates found so far...")
        
        logging.info(f"Scanning {ticker}...")

        try:
            # Fetch Yahoo Finance data
            logging.info(f"Fetching data for {ticker}...")
            stock_data = yf.Ticker(ticker).history(period="1mo")
            logging.info(f"{ticker}: Fetched {len(stock_data)} days of data")
            
            if len(stock_data) < 2:
                logging.warning(f"Skipping {ticker} - insufficient data (only {len(stock_data)} days)")
                continue

            # Log the data we got
            logging.info(f"{ticker}: Latest close: {stock_data['Close'].iloc[-1]:.2f}, Latest volume: {stock_data['Volume'].iloc[-1]}")

            # Calculate metrics with validation
            latest_open = stock_data['Open'].iloc[-1]
            latest_close = stock_data['Close'].iloc[-1]
            
            if latest_open == 0:
                logging.warning(f"Skipping {ticker} - zero open price")
                continue
                
            drop_pct = (latest_open - latest_close) / latest_open * 100

            # Calculate RSI with validation
            if len(stock_data) < 15:
                logging.warning(f"Skipping {ticker} - insufficient data for RSI calculation (need 15+ days, have {len(stock_data)})")
                continue
                
            rsi = calculate_rsi(stock_data['Close'], 14)
            
            # Calculate volume ratio
            mean_volume = stock_data['Volume'].mean()
            if mean_volume == 0:
                logging.warning(f"Skipping {ticker} - zero mean volume")
                continue
                
            volume_ratio = stock_data['Volume'].iloc[-1] / mean_volume

            logging.info(f"  Drop: {drop_pct:.2f}%, RSI: {rsi:.2f}, Volume: {volume_ratio:.2f}x")

            # Check if stock meets ALL criteria before calling LLM (using current parameters)
            meets_drop_criteria = params['drop_min'] <= drop_pct <= params['drop_max']
            meets_rsi_criteria = rsi < params['rsi_threshold']
            meets_volume_criteria = volume_ratio > params['volume_ratio_min']
            
            if not meets_drop_criteria:
                logging.info(f"  ❌ Rejected: Does not meet drop criteria (drop: {drop_pct:.1f}%, need {params['drop_min']}% to {params['drop_max']}%)")
                continue
            
            if not meets_rsi_criteria:
                logging.info(f"  ❌ Rejected: Does not meet RSI criteria (rsi: {rsi:.1f}, need < {params['rsi_threshold']})")
                continue
                
            if not meets_volume_criteria:
                logging.info(f"  ❌ Rejected: Does not meet volume criteria (vol_ratio: {volume_ratio:.1f}, need > {params['volume_ratio_min']})")
                continue

            # Stock meets ALL criteria - fetch news and analyze with LLM
            logging.info(f"  ✅ Passes filters")
            logging.info(f"  MEETS ALL CRITERIA - Fetching news headlines...")
            news_headlines = get_news_headlines(ticker, 3)
            logging.info(f"{ticker}: Found {len(news_headlines)} news headlines")

            # Analyze stock drop with LLM
            logging.info(f"{ticker}: Analyzing stock drop with LLM...")
            analysis = analyze_stock_drop(ticker, news_headlines, {'drop_pct': drop_pct, 'rsi': rsi})
            logging.info(f"{ticker}: Analysis complete")

            # Run FREE local pattern detection for technical confirmation
            logging.info(f"{ticker}: Running FREE pattern detection...")
            pattern_result = analyze_chart_patterns(ticker, price_data=stock_data, period='3mo', interval='1d')
            
            vision_signal = None
            if pattern_result['success']:
                vision_signal = pattern_to_signal(pattern_result['patterns'])
                signal_type = vision_signal['signal']
                signal_conf = vision_signal['confidence']
                signal_reasons = ', '.join(vision_signal['reasoning'][:2])  # First 2 reasons
                
                logging.info(f"{ticker}: Vision says {signal_type} ({signal_conf:.0%} confidence) - {signal_reasons}")
                
                # Bonus points if vision agrees (BUY or STRONG_BUY)
                if signal_type in ['BUY', 'STRONG_BUY']:
                    original_confidence = analysis['confidence']
                    analysis['confidence'] = min(analysis['confidence'] + 0.10, 1.0)
                    logging.info(f"{ticker}: Vision agrees! Confidence boost: {original_confidence:.2f} → {analysis['confidence']:.2f}")
                elif signal_type == 'AVOID':
                    original_confidence = analysis['confidence']
                    analysis['confidence'] = max(analysis['confidence'] - 0.15, 0.0)
                    logging.info(f"{ticker}: Vision says AVOID! Confidence reduced: {original_confidence:.2f} → {analysis['confidence']:.2f}")
            else:
                logging.warning(f"{ticker}: Pattern detection failed: {pattern_result.get('error', 'Unknown error')}")

            logging.info(f"{ticker}: CANDIDATE FOUND!")
            candidates.append({
                'ticker': ticker,
                'drop_pct': drop_pct,
                'rsi': rsi,
                'volume_ratio': volume_ratio,
                'news': news_headlines,
                'analysis': analysis,
                'vision_signal': vision_signal
            })

        except Exception as e:
            logging.error(f"Error scanning {ticker}: {type(e).__name__}: {str(e)}")
            logging.error(f"Full traceback for {ticker}:\n{traceback.format_exc()}")

    return sorted(candidates, key=lambda x: x['analysis']['confidence'], reverse=True)

def calculate_rsi(prices, n=14):
    """Calculate the Relative Strength Index (RSI)"""
    try:
        deltas = prices.diff()
        seed = deltas[:n+1]
        up = seed[seed >= 0].sum() / n
        down = -seed[seed < 0].sum() / n
        
        if down == 0:
            return 100.0  # If no down movement, RSI is 100
            
        rs = up / down
        rsi = 100 - (100 / (1 + rs))
        
        # Handle if rsi is a Series, get the last value
        if hasattr(rsi, 'iloc'):
            return rsi.iloc[-1]
        return rsi
    except Exception as e:
        logging.error(f"Error calculating RSI: {type(e).__name__}: {str(e)}")
        raise

def get_news_headlines(ticker, limit):
    """Fetch top news headlines for a stock from Yahoo Finance"""
    try:
        news = yf.Ticker(ticker).get_news()
        headlines = []
        for h in news[:limit]:
            if 'title' in h:
                headlines.append(h['title'])
            else:
                logging.warning(f"News item for {ticker} missing 'title' field: {h.keys()}")
        return headlines
    except Exception as e:
        logging.warning(f"Could not fetch news for {ticker}: {type(e).__name__}: {str(e)}")
        return []

if __name__ == "__main__":
    start_time = time.time()
    results = run_screener()
    end_time = time.time()

    print("Screening Results:")
    for result in results:
        print(f"{result['ticker']} - Drop: {result['drop_pct']:.1f}%, RSI: {result['rsi']:.1f}, Volume: {result['volume_ratio']:.1f}")
        print(f"  News: {', '.join(result['news'])}")
        print(f"  Analysis: {result['analysis']}")
        print()

    print(f"Found {len(results)} candidates in {end_time - start_time:.2f} seconds")

    # Save results to file
    filename = f"data/screening_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)
