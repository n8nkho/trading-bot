import requests
import datetime
import logging
import yfinance as yf

# Configure logging
logging.basicConfig(filename='logs/trump_trader.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

TRUMP_SIGNALS = {
    "tariffs_china": {
        "keywords": ["tariff china", "china trade war", "import tax china"],
        "buy": ["X", "NUE", "STLD"],
        "short": ["AAPL"],
        "hold_days": 2,
        "expected_gain": 0.05
    },
    "infrastructure": {
        "keywords": ["infrastructure bill", "rebuild america", "roads bridges"],
        "buy": ["CAT", "DE", "VMC", "MLM"],
        "hold_days": 3,
        "expected_gain": 0.04
    },
    "fed_criticism": {
        "keywords": ["fed powell", "interest rates too high", "cut rates"],
        "buy": ["GLD", "TLT"],
        "hold_days": 1,
        "expected_gain": 0.03
    },
    "crypto_support": {
        "keywords": ["bitcoin reserve", "crypto support", "digital currency"],
        "buy": ["COIN", "MARA", "RIOT"],
        "hold_days": 2,
        "expected_gain": 0.10
    },
    "energy_drilling": {
        "keywords": ["drill baby drill", "energy independence", "oil drilling"],
        "buy": ["XOM", "CVX", "OXY"],
        "hold_days": 2,
        "expected_gain": 0.05
    },
    "defense_spending": {
        "keywords": ["military budget", "defense spending", "nato funding"],
        "buy": ["LMT", "RTX", "NOC", "BA"],
        "hold_days": 3,
        "expected_gain": 0.04
    }
}

def fetch_trump_news():
    try:
        # Example URL for Google News RSS feed
        url = "https://news.google.com/rss/search?q=Trump&hl=en-US&gl=US&ceid=US:en"
        response = requests.get(url)
        response.raise_for_status()
        # Parse the RSS feed and extract headlines
        headlines = []  # Placeholder for actual parsing logic
        return headlines
    except requests.RequestException as e:
        logging.error(f"Error fetching Trump news: {e}")
        return []

def detect_policy_signal(headlines):
    best_match = None
    highest_confidence = 0
    for headline in headlines:
        for policy, details in TRUMP_SIGNALS.items():
            matches = sum(1 for keyword in details['keywords'] if keyword in headline.lower())
            confidence = matches / len(details['keywords'])
            if confidence > highest_confidence and confidence >= 0.7:
                highest_confidence = confidence
                best_match = {
                    'policy': policy,
                    'confidence': confidence,
                    'stocks_buy': details.get('buy', []),
                    'stocks_short': details.get('short', []),
                    'hold_days': details['hold_days'],
                    'headline': headline
                }
    return best_match

def calculate_position_size(portfolio_value, num_stocks):
    position_value = 0.1 * portfolio_value / num_stocks
    return position_value

def execute_trump_trade(signal, portfolio_value):
    trade_details = []
    for stock in signal['stocks_buy']:
        position_size = calculate_position_size(portfolio_value, len(signal['stocks_buy']))
        trade_details.append({
            'stock': stock,
            'position_size': position_size,
            'profit_target': position_size * (1 + signal['expected_gain']),
            'hold_days': signal['hold_days']
        })
        logging.info(f"Trade recommendation: Buy {stock}, Position size: {position_size}, "
                     f"Profit target: {position_size * (1 + signal['expected_gain'])}, "
                     f"Hold days: {signal['hold_days']}, Triggered by: {signal['headline']}")
    return trade_details

def monitor_trump_positions():
    # Placeholder for monitoring logic
    exit_recommendations = []  # Placeholder for actual exit logic
    return exit_recommendations

def trump_strategy(portfolio_value):
    headlines = fetch_trump_news()
    signal = detect_policy_signal(headlines)
    if signal:
        trades = execute_trump_trade(signal, portfolio_value)
        logging.info(f"Executed trades based on signal: {signal}")
    exit_recommendations = monitor_trump_positions()
    return {
        'trades': trades if signal else [],
        'exits': exit_recommendations
    }
