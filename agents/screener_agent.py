import os
import json
import time
import logging
import traceback
from datetime import datetime
from pathlib import Path
import yfinance as yf
from utils.local_llm import analyze_stock_drop
try:
    from utils.ai_router import ask_ai as _ask_ai
    _HAS_ROUTER = True
except ImportError:
    _HAS_ROUTER = False
from agents.vision_analyst import analyze_chart_patterns, pattern_to_signal

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

def get_vix() -> float:
    """Fetch current VIX level from Yahoo Finance."""
    try:
        vix = yf.Ticker("^VIX").history(period="2d")
        if not vix.empty:
            return float(vix["Close"].iloc[-1])
    except Exception as e:
        logging.warning(f"Could not fetch VIX: {e}")
    return 20.0  # default neutral


def _get_current_regime() -> str:
    """Read current regime from data/regime_state.json."""
    try:
        regime_file = Path(__file__).resolve().parent.parent / "data" / "regime_state.json"
        if regime_file.exists():
            import json as _json
            return _json.loads(regime_file.read_text()).get("regime", "NEUTRAL")
    except Exception:
        pass
    return "NEUTRAL"


def get_adaptive_params(base_params: dict) -> dict:
    """Adjust screening thresholds based on VIX and regime."""
    vix = get_vix()
    regime = _get_current_regime()
    params = base_params.copy()
    params["vix"] = vix
    if vix >= 40:
        params["halt"] = True
        logging.warning(f"VIX={vix:.1f} >= 40: CRISIS MODE - halting new entries")
    elif vix >= 25:
        params["drop_min"] = min(params.get("drop_min", -15), -7)
        params["rsi_threshold"] = min(params.get("rsi_threshold", 40), 35)
        params["volume_ratio_min"] = max(params.get("volume_ratio_min", 1.5), 2.0)
        params["halt"] = False
        logging.info(f"VIX={vix:.1f}: ELEVATED - tightened thresholds")
    elif vix < 15:
        params["drop_min"] = max(params.get("drop_min", -15), -12)
        params["rsi_threshold"] = min(params.get("rsi_threshold", 40), 38)
        params["volume_ratio_min"] = max(params.get("volume_ratio_min", 1.5), 1.8)
        params["halt"] = False
        logging.info(f"VIX={vix:.1f}: LOW VOL - slightly relaxed thresholds")
    elif regime == "BULL_TREND":
        params["drop_min"] = max(params.get("drop_min", -15), -12)
        params["rsi_threshold"] = max(params.get("rsi_threshold", 40), 42)
        params["volume_ratio_min"] = min(params.get("volume_ratio_min", 1.5), 1.3)
        params["halt"] = False
        logging.info(f"VIX={vix:.1f}, regime=BULL_TREND: RELAXED thresholds (RSI<42, drop>-12%, vol>1.3x)")
    else:
        params["halt"] = False
        logging.info(f"VIX={vix:.1f}, regime={regime}: NORMAL thresholds")
    return params


def run_screener():
    # Load current parameters (may have been auto-tuned)
    params = load_screening_params()
    params = get_adaptive_params(params)
    if params.get("halt"):
        logging.warning("VIX regime halt active — returning no candidates")
        return []
    
    with open('config/watchlist.json', 'r') as f:
        watchlist = json.load(f)['quality_stocks']

    candidates = []
    for stock in watchlist:
        ticker = stock['ticker']
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
            if _HAS_ROUTER:
                prompt = f"{ticker}: drop {drop_pct:.1f}%, RSI {rsi:.1f}. News: {news_headlines[:3]}. Analyze for contrarian entry."
                analysis = _ask_ai('analyze', prompt, ticker=ticker) or analyze_stock_drop(ticker, news_headlines, {'drop_pct': drop_pct, 'rsi': rsi})
            else:
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
    """Calculate RSI using Wilder's smoothing (EMA-based)."""
    try:
        delta = prices.diff().dropna()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=n-1, min_periods=n).mean()
        avg_loss = loss.ewm(com=n-1, min_periods=n).mean()
        rs = avg_gain / avg_loss.replace(0, float("inf"))
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])
    except Exception as e:
        logging.error(f"RSI calculation error: {e}")
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


def get_sp500_tickers():
    """
    Return a list of the top 100 most liquid S&P 500 tickers.
    Used by earnings_drift, insider_tracker, vwap_reversion, and defensive_universe_scanner.
    """
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'BRK.B',
        'UNH', 'XOM', 'JNJ', 'JPM', 'V', 'PG', 'MA', 'HD', 'CVX', 'MRK',
        'ABBV', 'KO', 'AVGO', 'PEP', 'COST', 'TMO', 'MCD', 'CSCO', 'ACN',
        'LLY', 'DHR', 'ABT', 'NKE', 'DIS', 'TXN', 'VZ', 'ADBE', 'WMT',
        'CRM', 'NFLX', 'ORCL', 'AMD', 'INTC', 'CMCSA', 'PFE', 'PM', 'BA',
        'QCOM', 'T', 'UNP', 'HON', 'IBM', 'GE', 'INTU', 'SBUX', 'CAT',
        'PLTR', 'COIN', 'HOOD', 'SOFI', 'RIVN', 'LCID', 'NIO',
        'SPY', 'QQQ', 'IWM', 'GLD', 'SLV', 'TLT', 'HYG', 'LQD',
        'MS', 'GS', 'BAC', 'WFC', 'C', 'BLK', 'SCHW', 'AXP',
        'AMGN', 'GILD', 'BIIB', 'REGN', 'VRTX', 'ISRG', 'MDT', 'BMY',
        'F', 'GM', 'UBER', 'LYFT', 'ABNB', 'DASH', 'SNAP', 'PINS',
        'ZM', 'DDOG', 'NET', 'SNOW', 'MDB', 'BILL', 'CRWD', 'PANW',
    ]
