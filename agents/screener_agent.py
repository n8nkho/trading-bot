import os
import json
import time
import logging
import traceback
from datetime import datetime
from pathlib import Path
import yfinance as yf
from utils.local_llm import analyze_stock_drop

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

def run_screener():
    # Load current parameters (may have been auto-tuned)
    params = load_screening_params()
    
    with open('config/watchlist.json', 'r') as f:
        watchlist = json.load(f)['quality_stocks']

    candidates = []
    for stock in watchlist:
        ticker = stock['ticker']
        logging.info(f"Scanning {ticker}")

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
            logging.info(f"{ticker}: Drop percentage: {drop_pct:.2f}%")
            
            # Calculate RSI with validation
            if len(stock_data) < 15:
                logging.warning(f"Skipping {ticker} - insufficient data for RSI calculation (need 15+ days, have {len(stock_data)})")
                continue
                
            rsi = calculate_rsi(stock_data['Close'], 14)
            logging.info(f"{ticker}: RSI: {rsi:.2f}")
            
            # Calculate volume ratio
            mean_volume = stock_data['Volume'].mean()
            if mean_volume == 0:
                logging.warning(f"Skipping {ticker} - zero mean volume")
                continue
                
            volume_ratio = stock_data['Volume'].iloc[-1] / mean_volume
            logging.info(f"{ticker}: Volume ratio: {volume_ratio:.2f}")

            # Check if stock meets ALL criteria before calling LLM (using current parameters)
            meets_drop_criteria = params['drop_min'] <= drop_pct <= params['drop_max']
            meets_rsi_criteria = rsi < params['rsi_threshold']
            meets_volume_criteria = volume_ratio > params['volume_ratio_min']
            
            if not meets_drop_criteria:
                logging.info(f"{ticker}: Does not meet drop criteria (drop: {drop_pct:.1f}%, need {params['drop_min']}% to {params['drop_max']}%)")
                continue
            
            if not meets_rsi_criteria:
                logging.info(f"{ticker}: Does not meet RSI criteria (rsi: {rsi:.1f}, need < {params['rsi_threshold']})")
                continue
                
            if not meets_volume_criteria:
                logging.info(f"{ticker}: Does not meet volume criteria (vol_ratio: {volume_ratio:.1f}, need > {params['volume_ratio_min']})")
                continue

            # Stock meets ALL criteria - fetch news and analyze with LLM
            logging.info(f"{ticker}: MEETS ALL CRITERIA - Fetching news headlines...")
            news_headlines = get_news_headlines(ticker, 3)
            logging.info(f"{ticker}: Found {len(news_headlines)} news headlines")

            # Analyze stock drop with LLM
            logging.info(f"{ticker}: Analyzing stock drop with LLM...")
            analysis = analyze_stock_drop(ticker, news_headlines, {'drop_pct': drop_pct, 'rsi': rsi})
            logging.info(f"{ticker}: Analysis complete")

            logging.info(f"{ticker}: CANDIDATE FOUND!")
            candidates.append({
                'ticker': ticker,
                'drop_pct': drop_pct,
                'rsi': rsi,
                'volume_ratio': volume_ratio,
                'news': news_headlines,
                'analysis': analysis
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
