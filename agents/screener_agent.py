import os
import json
import time
import logging
from datetime import datetime
import yfinance as yf
from utils.local_llm import analyze_stock_drop

logging.basicConfig(filename='logs/screener.log', level=logging.INFO)

def run_screener():
    with open('config/watchlist.json', 'r') as f:
        watchlist = json.load(f)['quality_stocks']

    candidates = []
    for stock in watchlist:
        ticker = stock['ticker']
        logging.info(f"Scanning {ticker}")

        try:
            # Fetch Yahoo Finance data
            stock_data = yf.Ticker(ticker).history(period="10d")
            if len(stock_data) < 2:
                logging.warning(f"Skipping {ticker} - insufficient data")
                continue

            # Calculate metrics
            drop_pct = (stock_data['Open'][-1] - stock_data['Close'][-1]) / stock_data['Open'][-1] * 100
            rsi = calculate_rsi(stock_data['Close'], 14)
            volume_ratio = stock_data['Volume'][-1] / stock_data['Volume'].mean()

            # Fetch news headlines
            news_headlines = get_news_headlines(ticker, 3)

            # Analyze stock drop
            analysis = analyze_stock_drop(ticker, news_headlines, {'drop_pct': drop_pct, 'rsi': rsi})

            # Filter for candidates
            if 5 <= abs(drop_pct) <= 15 and rsi < 40 and volume_ratio > 1.5:
                candidates.append({
                    'ticker': ticker,
                    'drop_pct': drop_pct,
                    'rsi': rsi,
                    'volume_ratio': volume_ratio,
                    'news': news_headlines,
                    'analysis': analysis
                })

        except Exception as e:
            logging.error(f"Error scanning {ticker}: {str(e)}")

    return sorted(candidates, key=lambda x: x['analysis']['confidence'], reverse=True)

def calculate_rsi(prices, n=14):
    """Calculate the Relative Strength Index (RSI)"""
    deltas = prices.diff()
    seed = deltas[:n+1]
    up = seed[seed >= 0].sum() / n
    down = -seed[seed < 0].sum() / n
    rs = up / down
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_news_headlines(ticker, limit):
    """Fetch top news headlines for a stock from Yahoo Finance"""
    try:
        news = yf.Ticker(ticker).get_news()
        return [h['title'] for h in news[:limit]]
    except:
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
