from __future__ import annotations

import logging
import os
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


def _entry_window_end_with_extension() -> tuple[int, int]:
    """Extend end of entry window by ENTRY_WINDOW_EXTEND_END_MINUTES (env, default 0)."""
    end_h, end_m = ENTRY_WINDOW_END
    try:
        extra = int(os.getenv("ENTRY_WINDOW_EXTEND_END_MINUTES", "0") or "0")
    except ValueError:
        extra = 0
    if extra <= 0:
        return end_h, end_m
    total = end_h * 60 + end_m + extra
    nh, nm = divmod(total, 60)
    if nh >= 24:
        return 23, 59
    return nh, nm

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
        return options_chain.calls, expiration_date
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
    result = get_options_chain(ticker, dte)
    if result is None:
        return None
    calls, expiration = result
    if calls.empty:
        return None
    
    atm_strike = min(calls['strike'], key=lambda x: abs(x - current_price))
    option = calls[calls['strike'] == atm_strike].iloc[0]
    
    return {
        'strike': atm_strike,
        'premium': option['lastPrice'],
        'bid': option['bid'],
        'ask': option['ask'],
        'volume': option['volume'],
        'expiration': expiration
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
            # This strategy currently only selects call options.
            'call': True,
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

    try:
        from agents.performance_analyzer import load_current_params

        _params = load_current_params()
        rsi_effective = float(_params.get("rsi_threshold", RSI_THRESHOLD))
    except Exception:
        rsi_effective = float(RSI_THRESHOLD)
    
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
                        'action': 'BUY',
                        'option_details': option_trade,
                        # Keys consumed by orchestrator/execution
                        'strike': option_trade['strike'],
                        'expiration': option_trade['expiration'],
                        'contracts': option_trade['contracts'],
                        'call': option_trade.get('call', True),
                        'entry_price': option_trade['premium'],  # option premium per share-equivalent
                        'position_size': option_trade['cost'],   # total premium cost
                        'confidence': stock_confidence,
                        'reason': 'Option trade offers better ROI'
                    }
                    logging.info(f"{ticker}: OPTION decision - {decision}")
                else:
                    decision = evaluate_single_entry(candidate, portfolio_value, rsi_threshold=rsi_effective)
                    decision['trade_type'] = 'STOCK'
                    # Do not overwrite SKIP reasons (RSI, window, stabilization, etc.).
                    if decision.get("action") == "BUY":
                        decision["reason"] = "Stock trade offers better ROI"
                    logging.info(f"{ticker}: STOCK decision - {decision}")
            else:
                decision = evaluate_single_entry(candidate, portfolio_value, rsi_threshold=rsi_effective)
                decision['trade_type'] = 'STOCK'
                if decision.get("action") == "BUY":
                    decision["reason"] = "No suitable option found (stock path)"
                logging.info(f"{ticker}: STOCK decision - {decision}")
            
            decisions.append(decision)
        except Exception as e:
            logging.error(f"Error evaluating {ticker}: {type(e).__name__}: {str(e)}")
            decisions.append({
                'ticker': ticker,
                'action': 'SKIP',
                'trade_type': 'NONE',
                'reason': f'Error during evaluation: {str(e)}',
                'position_size': 0,
                'shares': 0,
                'timestamp': datetime.now().isoformat()
            })
    
    buy_count = sum(1 for d in decisions if d['action'] == 'BUY')
    logging.info(f"Entry evaluation complete: {buy_count} BUY, {len(decisions) - buy_count} SKIP")
    
    return decisions

def create_skip_decision(ticker, reason):
    """Create a SKIP decision dict"""
    return {
        'ticker': ticker,
        'action': 'SKIP',
        'reason': reason,
        'position_size': 0,
        'shares': 0,
        'timestamp': datetime.now().isoformat()
    }

def evaluate_single_entry(candidate, portfolio_value, *, rsi_threshold: float | None = None):
    """
    Evaluate a single candidate for entry.
    
    Args:
        candidate: Candidate dict from screener with ticker, rsi, analysis, etc.
        portfolio_value: Current portfolio value
        rsi_threshold: Oversold ceiling (default: module RSI_THRESHOLD or align with data/current_params.json via evaluate_entry)
        
    Returns:
        Decision dict with action, reason, position_size, shares
    """
    ticker = candidate['ticker']
    screener_rsi = candidate.get('rsi', 100)
    rsi_cap = float(rsi_threshold) if rsi_threshold is not None else float(RSI_THRESHOLD)
    confidence = candidate.get('analysis', {}).get('confidence', 0.5)
    
    # Fetch current intraday data
    logging.info(f"{ticker}: Fetching intraday data...")
    stock = yf.Ticker(ticker)
    intraday_data = stock.history(period="1d", interval="1m")
    
    if len(intraday_data) == 0:
        logging.warning(f"{ticker}: No intraday data available")
        return create_skip_decision(ticker, "No intraday data available")
    
    # Get current price and day's low
    current_price = intraday_data['Close'].iloc[-1]
    day_low = intraday_data['Low'].min()
    day_high = intraday_data['High'].max()
    
    logging.info(f"{ticker}: Current price: ${current_price:.2f}, Day low: ${day_low:.2f}, Day high: ${day_high:.2f}")
    
    # Check 1: RSI must be extra oversold
    if screener_rsi >= rsi_cap:
        reason = f"RSI not oversold enough ({screener_rsi:.1f} >= {rsi_cap})"
        logging.info(f"{ticker}: {reason}")
        return create_skip_decision(ticker, reason)
    
    logging.info(f"{ticker}: ✓ RSI check passed ({screener_rsi:.1f} < {rsi_cap})")
    
    # Check 2: Price stabilization (current price > low * 1.02)
    stabilization_price = day_low * STABILIZATION_FACTOR
    if current_price <= stabilization_price:
        reason = f"Price not stabilized (${current_price:.2f} <= ${stabilization_price:.2f})"
        logging.info(f"{ticker}: {reason}")
        return create_skip_decision(ticker, reason)
    
    logging.info(f"{ticker}: ✓ Price stabilization check passed (${current_price:.2f} > ${stabilization_price:.2f})")
    
    # Check 3: Time of day (2:30-3:45 PM ET, optional extension via ENTRY_WINDOW_EXTEND_END_MINUTES)
    if not is_entry_window():
        current_time_et = get_current_time_et()
        eh, em = _entry_window_end_with_extension()
        reason = f"Outside entry window (current: {current_time_et.strftime('%H:%M')} ET, window: 14:30-{eh:02d}:{em:02d} ET)"
        logging.info(f"{ticker}: {reason}")
        return create_skip_decision(ticker, reason)
    
    current_time_et = get_current_time_et()
    logging.info(f"{ticker}: ✓ Time window check passed ({current_time_et.strftime('%H:%M')} ET)")
    
    # Calculate position size using fractional Kelly
    base_position = portfolio_value * BASE_POSITION_PCT
    adjusted_position = base_position * confidence
    position_size = min(adjusted_position, MAX_POSITION_SIZE)
    shares = int(position_size / current_price)
    
    # Ensure at least 1 share
    if shares < 1:
        reason = f"Position size too small (${position_size:.2f} < 1 share at ${current_price:.2f})"
        logging.info(f"{ticker}: {reason}")
        return create_skip_decision(ticker, reason)
    
    actual_position_size = shares * current_price
    
    logging.info(f"{ticker}: Position sizing - Base: ${base_position:.2f}, Confidence: {confidence:.2f}, Adjusted: ${adjusted_position:.2f}, Final: ${actual_position_size:.2f} ({shares} shares)")
    
    # All checks passed - BUY decision
    return {
        'ticker': ticker,
        'action': 'BUY',
        'reason': f'All entry criteria met: RSI={screener_rsi:.1f} (<{rsi_cap}), Price stabilized at ${current_price:.2f}, Time={current_time_et.strftime("%H:%M")} ET',
        'position_size': actual_position_size,
        'shares': shares,
        'entry_price': current_price,
        'confidence': confidence,
        'screener_data': {
            'drop_pct': candidate.get('drop_pct'),
            'rsi': screener_rsi,
            'volume_ratio': candidate.get('volume_ratio'),
            'news': candidate.get('news', [])
        },
        'timestamp': datetime.now().isoformat()
    }

def is_entry_window():
    """Check if current time is within entry window (2:30 PM ET through end, optionally extended)."""
    try:
        current_time = get_current_time_et()
        start_hour, start_min = ENTRY_WINDOW_START
        end_hour, end_min = _entry_window_end_with_extension()
        
        current_minutes = current_time.hour * 60 + current_time.minute
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min
        
        in_window = start_minutes <= current_minutes <= end_minutes
        
        if not in_window:
            logging.info(f"Outside entry window: {current_time.strftime('%H:%M')} ET (window: {start_hour:02d}:{start_min:02d}-{end_hour:02d}:{end_min:02d} ET)")
        
        return in_window
    except Exception as e:
        logging.error(f"Error checking entry window: {type(e).__name__}: {str(e)}")
        return False

def get_current_time_et():
    """Get current time in Eastern Time"""
    et_tz = pytz.timezone('US/Eastern')
    return datetime.now(et_tz)
