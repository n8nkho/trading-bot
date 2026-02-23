import logging
import yfinance as yf
from datetime import datetime
import pytz
import numpy as np

logging.basicConfig(
    filename='logs/entry.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Configuration
PORTFOLIO_VALUE = 50000  # Default portfolio value
BASE_POSITION_PCT = 0.05  # 5% of portfolio per position
MAX_POSITION_SIZE = 2000  # Maximum dollars per position
RSI_THRESHOLD = 35  # Extra oversold threshold
STABILIZATION_FACTOR = 1.02  # Price must be 2% above low
ENTRY_WINDOW_START = (14, 30)  # 2:30 PM ET
ENTRY_WINDOW_END = (15, 45)  # 3:45 PM ET

def get_options_chain(ticker, dte_target=35):
    """
    Fetch the options chain for a given ticker and find the expiration closest to the target DTE.
    
    Args:
        ticker: Stock ticker symbol
        dte_target: Target days to expiration
        
    Returns:
        DataFrame of call options or None if not available
    """
    try:
        stock = yf.Ticker(ticker)
        options_dates = stock.options
        if not options_dates:
            logging.warning(f"{ticker}: No options data available")
            return None
        
        expiration_date = next((date for date in options_dates if 30 <= (datetime.strptime(date, '%Y-%m-%d') - datetime.now()).days <= 45), None)
        if not expiration_date:
            logging.warning(f"{ticker}: No suitable expiration date found")
            return None
        
        options_chain = stock.option_chain(expiration_date)
        return options_chain.calls
    except Exception as e:
        logging.error(f"Error fetching options chain for {ticker}: {type(e).__name__}: {str(e)}")
        return None

def find_atm_option(ticker, current_price, dte=35):
    """
    Find the ATM option for a given ticker.
    
    Args:
        ticker: Stock ticker symbol
        current_price: Current stock price
        dte: Days to expiration
        
    Returns:
        Dict with option details or None if not suitable
    """
    calls = get_options_chain(ticker, dte)
    if calls is None or calls.empty:
        return None
    
    atm_strike = min(calls['strike'], key=lambda x: abs(x - current_price))
    option = calls[calls['strike'] == atm_strike].iloc[0]
    
    return {
        'strike': atm_strike,
        'premium': option['lastPrice'],
        'bid': option['bid'],
        'ask': option['ask'],
        'volume': option['volume'],
        'expiration': option['expiration']
    }

def evaluate_option_trade(ticker, current_price, stock_confidence):
    """
    Evaluate an option trade for a given ticker.
    
    Args:
        ticker: Stock ticker symbol
        current_price: Current stock price
        stock_confidence: Confidence level for stock trade
        
    Returns:
        Dict with option trade details or None if not suitable
    """
    option = find_atm_option(ticker, current_price)
    if option is None:
        return None
    
    premium = option['premium']
    bid = option['bid']
    ask = option['ask']
    strike = option['strike']
    expiration = option['expiration']
    
    bid_ask_spread_pct = (ask - bid) / premium * 100
    breakeven = strike + premium
    leverage = current_price / (premium * 100)
    max_contracts = min(3, int(500 / (premium * 100)))
    
    if (bid_ask_spread_pct < 15 and
        option['volume'] > 100 and
        premium * 100 < 500 and
        premium > 0.50):
        return {
            'ticker': ticker,
            'type': 'OPTION',
            'strike': strike,
            'expiration': expiration,
            'premium': premium,
            'contracts': max_contracts,
            'cost': max_contracts * premium * 100,
            'breakeven': breakeven,
            'leverage': leverage,
            'bid_ask_spread_pct': bid_ask_spread_pct
        }
    return None
    """
    Evaluate options entry for a given ticker.
    
    Args:
        ticker: Stock ticker symbol
        current_price: Current stock price
        metrics: Additional metrics for decision making
        
    Returns:
        Decision dict with action, reason, position_size, contracts, option details
    """
    logging.info(f"Evaluating options entry for {ticker}")
    
    # Fetch options chain
    stock = yf.Ticker(ticker)
    options_dates = stock.options
    if not options_dates:
        logging.warning(f"{ticker}: No options data available")
        return create_skip_decision(ticker, "No options data available")
    
    # Select expiration date 30-45 days out
    expiration_date = next((date for date in options_dates if 30 <= (datetime.strptime(date, '%Y-%m-%d') - datetime.now()).days <= 45), None)
    if not expiration_date:
        logging.warning(f"{ticker}: No suitable expiration date found")
        return create_skip_decision(ticker, "No suitable expiration date found")
    
    options_chain = stock.option_chain(expiration_date)
    calls = options_chain.calls
    
    # Calculate ATM strike
    atm_strike = min(calls['strike'], key=lambda x: abs(x - current_price))
    
    # Filter for ATM or slightly OTM calls
    calls = calls[(calls['strike'] >= atm_strike) & (calls['strike'] <= atm_strike * 1.05)]
    
    # Filter for delta 0.5-0.7
    calls = calls[(calls['delta'] >= 0.5) & (calls['delta'] <= 0.7)]
    
    # Filter for liquidity (bid-ask spread < 10% of premium)
    calls = calls[(calls['ask'] - calls['bid']) / calls['bid'] < 0.1]
    
    # Filter for IV rank < 50%
    calls = calls[calls['impliedVolatility'] < 0.5]
    
    if calls.empty:
        logging.warning(f"{ticker}: No suitable options found")
        return create_skip_decision(ticker, "No suitable options found")
    
    # Select the best option based on criteria
    best_option = calls.iloc[0]
    premium = best_option['ask']
    strike = best_option['strike']
    breakeven = strike + premium
    
    # Calculate potential returns
    stock_return = (current_price - strike) / strike
    option_return = (breakeven - current_price) / premium
    
    # Decision based on better return
    if option_return > stock_return:
        # Calculate position sizing
        max_premium = 500
        contracts = int(max_premium / premium)
        
        logging.info(f"{ticker}: Option trade selected - Strike: {strike}, Expiration: {expiration_date}, Premium: {premium}, Contracts: {contracts}")
        
        return {
            'ticker': ticker,
            'action': 'BUY_OPTION',
            'reason': f'Option trade selected: Strike={strike}, Expiration={expiration_date}, Premium={premium}',
            'position_size': contracts * premium * 100,
            'contracts': contracts,
            'option_details': {
                'strike': strike,
                'expiration': expiration_date,
                'premium': premium
            },
            'timestamp': datetime.now().isoformat()
        }
    else:
        logging.info(f"{ticker}: Stock trade selected over option")
        return create_skip_decision(ticker, "Stock trade selected over option")
def evaluate_entry(candidates, portfolio_value=PORTFOLIO_VALUE):
    """
    Evaluate entry decisions for screened candidates.
    
    Args:
        candidates: List of candidate stocks from screener
        portfolio_value: Current portfolio value for position sizing
        
    Returns:
        List of entry decisions with BUY/SKIP and reasoning
    """
    logging.info(f"Starting entry evaluation for {len(candidates)} candidates")
    logging.info(f"Portfolio value: ${portfolio_value:,.2f}")
    
    decisions = []
    
    for candidate in candidates:
        ticker = candidate['ticker']
        logging.info(f"Evaluating entry for {ticker}")
        
        try:
            current_price = candidate['current_price']
            stock_confidence = candidate.get('analysis', {}).get('confidence', 0.5)
            
            stock_roi = stock_confidence * 0.05
            option_trade = evaluate_option_trade(ticker, current_price, stock_confidence)
            
            if option_trade:
                option_roi = stock_confidence * 0.50
                if option_roi > stock_roi * 2:
                    decision = {
                        'ticker': ticker,
                        'trade_type': 'OPTION',
                        'option_details': option_trade,
                        'reason': 'Option trade offers better ROI'
                    }
                    logging.info(f"{ticker}: OPTION decision - {decision}")
                else:
                    decision = evaluate_single_entry(candidate, portfolio_value)
                    decision['trade_type'] = 'STOCK'
                    decision['reason'] = 'Stock trade offers better ROI'
                    logging.info(f"{ticker}: STOCK decision - {decision}")
            else:
                decision = evaluate_single_entry(candidate, portfolio_value)
                decision['trade_type'] = 'STOCK'
                decision['reason'] = 'No suitable option found'
                logging.info(f"{ticker}: STOCK decision - {decision}")
            
            decisions.append(decision)
        except Exception as e:
            logging.error(f"Error evaluating {ticker}: {type(e).__name__}: {str(e)}")
            decisions.append({
                'ticker': ticker,
                'action': 'SKIP',
                'reason': f'Error during evaluation: {str(e)}',
                'position_size': 0,
                'shares': 0,
                'timestamp': datetime.now().isoformat()
            })
    
    buy_count = sum(1 for d in decisions if d['action'] == 'BUY')
    logging.info(f"Entry evaluation complete: {buy_count} BUY, {len(decisions) - buy_count} SKIP")
    
    return decisions
