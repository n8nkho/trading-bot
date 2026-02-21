"""
Trading System Orchestrator
Coordinates the complete workflow: screening, entry evaluation, risk management, and position monitoring
"""

import json
import logging
import os
from datetime import datetime, time
from pathlib import Path
import pytz
from dotenv import load_dotenv

# Import Alpaca
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# Import agents
from agents.screener_agent import run_screener
from agents.entry_agent import evaluate_entry
from agents.exit_monitor import monitor_positions as monitor_exit_conditions
from agents.risk_guardian import check_risk_limits, get_risk_status
from agents.performance_analyzer import track_decision, load_current_params
from agents.llama_watchdog import run_watchdog, preload_models, is_emergency_mode
from utils.grok_sentiment import check_twitter_sentiment

# Load environment variables
load_dotenv()

# Setup logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "orchestrator.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Configuration
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

POSITIONS_FILE = DATA_DIR / "positions.json"
PORTFOLIO_VALUE = 50000  # Default portfolio value

# Market hours (Eastern Time)
MARKET_OPEN = time(9, 30)   # 9:30 AM ET
MARKET_CLOSE = time(16, 0)  # 4:00 PM ET

# Screening configuration
GROK_CONFIDENCE_THRESHOLD = 0.8  # Only use Grok for high-confidence candidates

# Trading configuration
MAX_POSITIONS = 5  # Maximum number of open positions
BUYING_POWER_BUFFER = 1.2  # Require 20% buffer on buying power

# Initialize Alpaca client (paper trading only)
ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
ALPACA_BASE_URL = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')

# Verify paper trading URL
if ALPACA_BASE_URL and 'paper' not in ALPACA_BASE_URL.lower():
    logger.error("SAFETY CHECK FAILED: Not using paper trading URL!")
    logger.error(f"Current URL: {ALPACA_BASE_URL}")
    logger.error("Please set ALPACA_BASE_URL to paper trading endpoint")
    raise ValueError("Must use paper trading URL for safety")

alpaca_client = None
if ALPACA_API_KEY and ALPACA_SECRET_KEY:
    try:
        alpaca_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
        logger.info(f"Alpaca client initialized (PAPER TRADING): {ALPACA_BASE_URL}")
    except Exception as e:
        logger.error(f"Failed to initialize Alpaca client: {type(e).__name__}: {str(e)}")
else:
    logger.warning("Alpaca credentials not found. Trading execution disabled.")

def get_account_info():
    """
    Get Alpaca account information including buying power.
    
    Returns:
        dict: {
            'buying_power': float,
            'equity': float,
            'cash': float,
            'portfolio_value': float,
            'position_count': int
        } or None if error
    """
    if not alpaca_client:
        logger.error("Alpaca client not initialized")
        return None
    
    try:
        account = alpaca_client.get_account()
        
        info = {
            'buying_power': float(account.buying_power),
            'equity': float(account.equity),
            'cash': float(account.cash),
            'portfolio_value': float(account.portfolio_value),
            'position_count': len(alpaca_client.get_all_positions())
        }
        
        logger.info(f"Account info: Buying power=${info['buying_power']:,.2f}, "
                   f"Equity=${info['equity']:,.2f}, Positions={info['position_count']}")
        
        return info
        
    except Exception as e:
        logger.error(f"Error getting account info: {type(e).__name__}: {str(e)}")
        return None


def is_market_hours():
    """
    Check if current time is during market hours (9:30 AM - 4:00 PM ET, Mon-Fri).
    
    Returns:
        bool: True if market is open
    """
    try:
        et_tz = pytz.timezone('US/Eastern')
        now_et = datetime.now(et_tz)
        
        # Check if weekday (0=Monday, 6=Sunday)
        if now_et.weekday() >= 5:  # Saturday or Sunday
            logger.info(f"Market closed: Weekend ({now_et.strftime('%A')})")
            return False
        
        # Check if within market hours
        current_time = now_et.time()
        if MARKET_OPEN <= current_time <= MARKET_CLOSE:
            return True
        else:
            logger.info(f"Market closed: Outside hours ({current_time.strftime('%H:%M')} ET)")
            return False
            
    except Exception as e:
        logger.error(f"Error checking market hours: {type(e).__name__}: {str(e)}")
        return False


def execute_buy_order(ticker, shares, entry_price):
    """
    Execute a market buy order via Alpaca.
    
    Args:
        ticker: Stock symbol
        shares: Number of shares to buy
        entry_price: Expected entry price (for logging)
        
    Returns:
        dict: {
            'success': bool,
            'order_id': str or None,
            'filled_qty': int or None,
            'filled_price': float or None,
            'error': str or None
        }
    """
    if not alpaca_client:
        logger.error(f"{ticker}: Cannot execute order - Alpaca client not initialized")
        return {
            'success': False,
            'order_id': None,
            'filled_qty': None,
            'filled_price': None,
            'error': 'Alpaca client not initialized'
        }
    
    try:
        logger.info(f"{ticker}: Submitting BUY order for {shares} shares (expected price: ${entry_price:.2f})")
        
        # Create market order request
        order_data = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        
        # Submit order
        order = alpaca_client.submit_order(order_data)
        
        logger.info(f"{ticker}: Order submitted - ID: {order.id}, Status: {order.status}")
        
        # Return order details
        return {
            'success': True,
            'order_id': str(order.id),
            'filled_qty': int(order.filled_qty) if order.filled_qty else None,
            'filled_price': float(order.filled_avg_price) if order.filled_avg_price else None,
            'status': str(order.status),
            'error': None
        }
        
    except Exception as e:
        logger.error(f"{ticker}: Error executing buy order: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'order_id': None,
            'filled_qty': None,
            'filled_price': None,
            'error': f"{type(e).__name__}: {str(e)}"
        }


def execute_sell_order(ticker, shares):
    """
    Execute a market sell order via Alpaca.
    
    Args:
        ticker: Stock symbol
        shares: Number of shares to sell
        
    Returns:
        dict: {
            'success': bool,
            'order_id': str or None,
            'filled_qty': int or None,
            'filled_price': float or None,
            'error': str or None
        }
    """
    if not alpaca_client:
        logger.error(f"{ticker}: Cannot execute order - Alpaca client not initialized")
        return {
            'success': False,
            'order_id': None,
            'filled_qty': None,
            'filled_price': None,
            'error': 'Alpaca client not initialized'
        }
    
    try:
        logger.info(f"{ticker}: Submitting SELL order for {shares} shares")
        
        # Create market order request
        order_data = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )
        
        # Submit order
        order = alpaca_client.submit_order(order_data)
        
        logger.info(f"{ticker}: Order submitted - ID: {order.id}, Status: {order.status}")
        
        # Return order details
        return {
            'success': True,
            'order_id': str(order.id),
            'filled_qty': int(order.filled_qty) if order.filled_qty else None,
            'filled_price': float(order.filled_avg_price) if order.filled_avg_price else None,
            'status': str(order.status),
            'error': None
        }
        
    except Exception as e:
        logger.error(f"{ticker}: Error executing sell order: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'order_id': None,
            'filled_qty': None,
            'filled_price': None,
            'error': f"{type(e).__name__}: {str(e)}"
        }


def run_daily_screening(portfolio_value=PORTFOLIO_VALUE):
    """
    Run the complete daily screening workflow.
    
    Workflow:
    1. Run screener to find beaten-down stocks
    2. For high-confidence candidates (>0.8), check Grok sentiment
    3. Evaluate entry timing and conditions
    4. Check risk limits for each approved entry
    5. Return approved trades with position sizes
    6. Save results to data/daily_signals_YYYYMMDD.json
    
    Args:
        portfolio_value: Current portfolio value for position sizing
        
    Returns:
        dict: {
            'timestamp': ISO timestamp,
            'candidates_found': int,
            'approved_trades': list of trade dicts,
            'rejected_trades': list of rejection dicts,
            'risk_status': current risk status
        }
    """
    logger.info("=" * 80)
    logger.info("STARTING DAILY SCREENING WORKFLOW")
    logger.info("=" * 80)
    
    start_time = datetime.now()
    
    try:
        # Step 1: Run screener
        logger.info("Step 1: Running stock screener...")
        candidates = run_screener()
        logger.info(f"Screener found {len(candidates)} candidates")
        
        if len(candidates) == 0:
            logger.info("No candidates found. Ending workflow.")
            result = {
                'timestamp': datetime.now().isoformat(),
                'candidates_found': 0,
                'approved_trades': [],
                'rejected_trades': [],
                'risk_status': get_risk_status()
            }
            save_daily_signals(result)
            return result
        
        # Step 2: Check Grok sentiment for high-confidence candidates
        logger.info("Step 2: Checking Grok sentiment for high-confidence candidates...")
        for candidate in candidates:
            confidence = candidate.get('analysis', {}).get('confidence', 0)
            ticker = candidate['ticker']
            
            if confidence >= GROK_CONFIDENCE_THRESHOLD:
                logger.info(f"{ticker}: High confidence ({confidence:.2f}) - checking Grok sentiment...")
                sentiment = check_twitter_sentiment(ticker, confidence)
                candidate['grok_sentiment'] = sentiment
                
                if sentiment:
                    logger.info(f"{ticker}: Grok sentiment = {sentiment}")
                    
                    # Adjust confidence based on sentiment
                    if sentiment == "BEARISH":
                        original_confidence = confidence
                        candidate['analysis']['confidence'] = confidence * 0.7  # Reduce by 30%
                        logger.warning(f"{ticker}: Confidence reduced from {original_confidence:.2f} to {confidence*0.7:.2f} due to bearish sentiment")
                    elif sentiment == "BULLISH":
                        original_confidence = confidence
                        candidate['analysis']['confidence'] = min(confidence * 1.1, 1.0)  # Increase by 10%, cap at 1.0
                        logger.info(f"{ticker}: Confidence increased from {original_confidence:.2f} to {min(confidence*1.1, 1.0):.2f} due to bullish sentiment")
            else:
                logger.info(f"{ticker}: Confidence {confidence:.2f} below threshold {GROK_CONFIDENCE_THRESHOLD} - skipping Grok")
                candidate['grok_sentiment'] = None
        
        # Step 3: Evaluate entry timing and conditions
        logger.info("Step 3: Evaluating entry conditions...")
        entry_decisions = evaluate_entry(candidates, portfolio_value)
        
        buy_decisions = [d for d in entry_decisions if d['action'] == 'BUY']
        skip_decisions = [d for d in entry_decisions if d['action'] == 'SKIP']
        
        logger.info(f"Entry evaluation: {len(buy_decisions)} BUY, {len(skip_decisions)} SKIP")
        
        # Step 4: Check account and risk limits
        logger.info("Step 4: Checking account status and risk limits...")
        
        # Get account info
        account_info = get_account_info()
        if not account_info:
            logger.error("Failed to get account info. Cannot proceed with trading.")
            result = {
                'timestamp': datetime.now().isoformat(),
                'error': 'Failed to get account info',
                'candidates_found': len(candidates),
                'approved_trades': [],
                'rejected_trades': [],
                'risk_status': get_risk_status()
            }
            save_daily_signals(result)
            return result
        
        # Check position limit
        if account_info['position_count'] >= MAX_POSITIONS:
            logger.warning(f"Position limit reached: {account_info['position_count']}/{MAX_POSITIONS}")
            logger.warning("Skipping all trades")
            result = {
                'timestamp': datetime.now().isoformat(),
                'candidates_found': len(candidates),
                'approved_trades': [],
                'rejected_trades': [{'ticker': d['ticker'], 'reason': 'Position limit reached'} for d in buy_decisions],
                'risk_status': get_risk_status(),
                'account_info': account_info
            }
            save_daily_signals(result)
            return result
        
        # Load current positions
        current_positions = load_positions()
        
        # Load current parameters (may have been auto-tuned)
        current_params = load_current_params()
        logger.info(f"Using parameters: RSI<{current_params['rsi_threshold']}, Stop Loss: {current_params['stop_loss_pct']}%")
        
        # Build portfolio data for risk checks
        portfolio_data = build_portfolio_data(current_positions, portfolio_value)
        
        approved_trades = []
        rejected_trades = []
        
        for decision in buy_decisions:
            ticker = decision['ticker']
            logger.info(f"{ticker}: Checking risk limits...")
            
            # Check position limit
            if account_info['position_count'] + len(approved_trades) >= MAX_POSITIONS:
                logger.warning(f"{ticker}: Position limit would be exceeded")
                rejected_trades.append({
                    'ticker': ticker,
                    'reason': f'Position limit ({MAX_POSITIONS}) would be exceeded',
                    'original_decision': decision
                })
                continue
            
            # Check buying power
            required_capital = decision['position_size'] * BUYING_POWER_BUFFER
            if account_info['buying_power'] < required_capital:
                logger.warning(f"{ticker}: Insufficient buying power (need ${required_capital:,.2f}, have ${account_info['buying_power']:,.2f})")
                rejected_trades.append({
                    'ticker': ticker,
                    'reason': f'Insufficient buying power (need ${required_capital:,.2f} with buffer)',
                    'original_decision': decision
                })
                continue
            
            # Build new position dict for risk check
            new_position = {
                'ticker': ticker,
                'size': decision['shares'],
                'value': decision['position_size'],
                'sector': get_sector_from_candidates(ticker, candidates)
            }
            
            # Check risk limits
            risk_check = check_risk_limits(portfolio_data, new_position)
            
            if risk_check['approved']:
                logger.info(f"{ticker}: APPROVED - {risk_check['reason']}")
                
                # Check if position size was adjusted
                if 'adjusted_size' in risk_check:
                    decision['shares'] = int(risk_check['adjusted_size'])
                    decision['position_size'] = decision['shares'] * decision['entry_price']
                    decision['risk_adjusted'] = True
                    logger.info(f"{ticker}: Position size adjusted to {decision['shares']} shares")
                else:
                    decision['risk_adjusted'] = False
                
                decision['risk_check'] = risk_check
                approved_trades.append(decision)
                
                # Track decision for performance analysis
                signal_id = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                track_decision(signal_id, {
                    'ticker': ticker,
                    'action': 'BUY',
                    'entry_price': decision['entry_price'],
                    'shares': decision['shares'],
                    'position_size': decision['position_size'],
                    'confidence': decision['confidence'],
                    'reasoning': decision['reasoning'],
                    'metrics': {
                        'rsi': decision.get('rsi'),
                        'drop_pct': decision.get('drop_pct'),
                        'volume_ratio': decision.get('volume_ratio'),
                        'confidence': decision['confidence']
                    },
                    'grok_sentiment': decision.get('grok_sentiment'),
                    'timestamp': datetime.now().isoformat()
                })
                
                # Update portfolio data for next iteration
                portfolio_data['positions'].append({
                    'ticker': ticker,
                    'value': decision['position_size'],
                    'sector': new_position['sector']
                })
                
                # Track decision for performance analysis
                signal_id = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                track_decision(signal_id, {
                    'ticker': ticker,
                    'action': 'BUY',
                    'entry_price': decision['entry_price'],
                    'shares': decision['shares'],
                    'position_size': decision['position_size'],
                    'confidence': decision['confidence'],
                    'reasoning': decision['reasoning'],
                    'metrics': {
                        'rsi': decision.get('rsi'),
                        'drop_pct': decision.get('drop_pct'),
                        'volume_ratio': decision.get('volume_ratio'),
                        'confidence': decision['confidence']
                    },
                    'grok_sentiment': decision.get('grok_sentiment'),
                    'timestamp': datetime.now().isoformat()
                })
                
                # Update portfolio data for next iteration
                portfolio_data['positions'].append({
                    'ticker': ticker,
                    'value': decision['position_size'],
                    'sector': new_position['sector']
                })
            else:
                logger.warning(f"{ticker}: REJECTED - {risk_check['reason']}")
                rejected_trades.append({
                    'ticker': ticker,
                    'reason': risk_check['reason'],
                    'original_decision': decision
                })
        
        # Step 5: Execute approved trades
        logger.info("Step 5: Executing approved trades...")
        
        executed_trades = []
        execution_failures = []
        
        for trade in approved_trades:
            ticker = trade['ticker']
            shares = trade['shares']
            entry_price = trade['entry_price']
            
            # Execute buy order
            order_result = execute_buy_order(ticker, shares, entry_price)
            
            if order_result['success']:
                logger.info(f"{ticker}: Order executed successfully - ID: {order_result['order_id']}")
                
                # Add order info to trade
                trade['order_id'] = order_result['order_id']
                trade['order_status'] = order_result['status']
                trade['filled_qty'] = order_result['filled_qty']
                trade['filled_price'] = order_result['filled_price']
                trade['executed'] = True
                trade['execution_time'] = datetime.now().isoformat()
                
                executed_trades.append(trade)
                
                # Add to positions file
                add_position({
                    'ticker': ticker,
                    'shares': shares,
                    'entry_price': entry_price,
                    'entry_date': datetime.now().isoformat(),
                    'order_id': order_result['order_id'],
                    'sector': get_sector_from_candidates(ticker, candidates),
                    'stop_loss_pct': current_params['stop_loss_pct'],
                    'take_profit_pct': current_params.get('take_profit_pct', 15.0)
                })
                
            else:
                logger.error(f"{ticker}: Order execution failed - {order_result['error']}")
                trade['executed'] = False
                trade['execution_error'] = order_result['error']
                execution_failures.append(trade)
        
        # Step 6: Compile results
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        result = {
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'candidates_found': len(candidates),
            'candidates': candidates,
            'approved_trades': approved_trades,
            'executed_trades': executed_trades,
            'execution_failures': execution_failures,
            'rejected_trades': rejected_trades,
            'risk_status': get_risk_status(),
            'portfolio_value': portfolio_value,
            'account_info': account_info
        }
        
        logger.info("=" * 80)
        logger.info(f"DAILY SCREENING COMPLETE: {len(executed_trades)} executed, {len(execution_failures)} failed, {len(rejected_trades)} rejected")
        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info("=" * 80)
        
        # Step 7: Save results
        save_daily_signals(result)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in daily screening workflow: {type(e).__name__}: {str(e)}")
        logger.error(f"Traceback:", exc_info=True)
        
        # Return error result
        result = {
            'timestamp': datetime.now().isoformat(),
            'error': str(e),
            'error_type': type(e).__name__,
            'candidates_found': 0,
            'approved_trades': [],
            'rejected_trades': [],
            'risk_status': get_risk_status()
        }
        save_daily_signals(result)
        return result


def monitor_positions():
    """
    Monitor open positions and generate exit signals.
    
    Workflow:
    1. Load open positions from data/positions.json
    2. Check if market is open
    3. Run exit monitoring for each position
    4. Save exit signals to data/exit_signals_YYYYMMDD.json
    
    Returns:
        dict: {
            'timestamp': ISO timestamp,
            'positions_monitored': int,
            'exit_signals': list of exit decision dicts,
            'market_open': bool
        }
    """
    logger.info("=" * 80)
    logger.info("STARTING POSITION MONITORING")
    logger.info("=" * 80)
    
    start_time = datetime.now()
    
    try:
        # Check if market is open
        market_open = is_market_hours()
        
        if not market_open:
            logger.info("Market is closed. Skipping position monitoring.")
            result = {
                'timestamp': datetime.now().isoformat(),
                'market_open': False,
                'positions_monitored': 0,
                'exit_signals': []
            }
            return result
        
        # Load open positions
        positions = load_positions()
        
        if len(positions) == 0:
            logger.info("No open positions to monitor.")
            result = {
                'timestamp': datetime.now().isoformat(),
                'market_open': True,
                'positions_monitored': 0,
                'exit_signals': []
            }
            return result
        
        logger.info(f"Monitoring {len(positions)} open positions...")
        
        # Run exit monitoring
        exit_signals = monitor_exit_conditions(positions)
        
        # Count actions
        action_counts = {}
        for signal in exit_signals:
            action = signal['action']
            action_counts[action] = action_counts.get(action, 0) + 1
        
        logger.info(f"Exit monitoring complete: {action_counts}")
        
        # Execute sell orders for exit signals
        logger.info("Executing exit orders...")
        
        executed_exits = []
        exit_failures = []
        
        for signal in exit_signals:
            if signal['action'] in ['SELL_ALL', 'SELL_HALF']:
                ticker = signal['ticker']
                sell_qty = signal.get('sell_qty', 0)
                
                if sell_qty > 0:
                    # Execute sell order
                    order_result = execute_sell_order(ticker, sell_qty)
                    
                    if order_result['success']:
                        logger.info(f"{ticker}: Exit order executed - ID: {order_result['order_id']}")
                        
                        signal['order_id'] = order_result['order_id']
                        signal['order_status'] = order_result['status']
                        signal['filled_qty'] = order_result['filled_qty']
                        signal['filled_price'] = order_result['filled_price']
                        signal['executed'] = True
                        signal['execution_time'] = datetime.now().isoformat()
                        
                        executed_exits.append(signal)
                        
                        # Update positions file
                        if signal['action'] == 'SELL_ALL':
                            remove_position(ticker)
                        else:  # SELL_HALF
                            update_position_quantity(ticker, sell_qty)
                        
                    else:
                        logger.error(f"{ticker}: Exit order failed - {order_result['error']}")
                        signal['executed'] = False
                        signal['execution_error'] = order_result['error']
                        exit_failures.append(signal)
        
        # Compile results
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        result = {
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'market_open': True,
            'positions_monitored': len(positions),
            'exit_signals': exit_signals,
            'executed_exits': executed_exits,
            'exit_failures': exit_failures,
            'action_summary': action_counts
        }
        
        logger.info("=" * 80)
        logger.info(f"POSITION MONITORING COMPLETE: {len(executed_exits)} exits executed, {len(exit_failures)} failed")
        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info("=" * 80)
        
        # Save exit signals
        save_exit_signals(result)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in position monitoring: {type(e).__name__}: {str(e)}")
        logger.error(f"Traceback:", exc_info=True)
        
        # Return error result
        result = {
            'timestamp': datetime.now().isoformat(),
            'error': str(e),
            'error_type': type(e).__name__,
            'market_open': is_market_hours(),
            'positions_monitored': 0,
            'exit_signals': []
        }
        save_exit_signals(result)
        return result


def load_positions():
    """
    Load open positions from data/positions.json.
    
    Returns:
        list: List of position dicts
    """
    try:
        if not POSITIONS_FILE.exists():
            logger.info(f"Positions file not found: {POSITIONS_FILE}")
            return []
        
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
        
        positions = data.get('positions', [])
        logger.info(f"Loaded {len(positions)} positions from {POSITIONS_FILE}")
        return positions
        
    except Exception as e:
        logger.error(f"Error loading positions: {type(e).__name__}: {str(e)}")
        return []


def add_position(position):
    """
    Add a new position to data/positions.json.
    
    Args:
        position: Position dict with ticker, shares, entry_price, etc.
    """
    try:
        # Load existing positions
        positions = load_positions()
        
        # Add new position
        positions.append(position)
        
        # Save back to file
        with open(POSITIONS_FILE, 'w') as f:
            json.dump({'positions': positions, 'last_updated': datetime.now().isoformat()}, f, indent=2)
        
        logger.info(f"Added position: {position['ticker']} - {position['shares']} shares @ ${position['entry_price']:.2f}")
        
    except Exception as e:
        logger.error(f"Error adding position: {type(e).__name__}: {str(e)}")


def remove_position(ticker):
    """
    Remove a position from data/positions.json.
    
    Args:
        ticker: Stock ticker to remove
    """
    try:
        # Load existing positions
        positions = load_positions()
        
        # Remove position
        positions = [p for p in positions if p['ticker'] != ticker]
        
        # Save back to file
        with open(POSITIONS_FILE, 'w') as f:
            json.dump({'positions': positions, 'last_updated': datetime.now().isoformat()}, f, indent=2)
        
        logger.info(f"Removed position: {ticker}")
        
    except Exception as e:
        logger.error(f"Error removing position: {type(e).__name__}: {str(e)}")


def update_position_quantity(ticker, qty_sold):
    """
    Update position quantity after partial sale.
    
    Args:
        ticker: Stock ticker
        qty_sold: Number of shares sold
    """
    try:
        # Load existing positions
        positions = load_positions()
        
        # Update position
        for pos in positions:
            if pos['ticker'] == ticker:
                old_qty = pos['shares']
                pos['shares'] = old_qty - qty_sold
                logger.info(f"Updated position: {ticker} - {old_qty} -> {pos['shares']} shares")
                break
        
        # Save back to file
        with open(POSITIONS_FILE, 'w') as f:
            json.dump({'positions': positions, 'last_updated': datetime.now().isoformat()}, f, indent=2)
        
    except Exception as e:
        logger.error(f"Error updating position quantity: {type(e).__name__}: {str(e)}")


def build_portfolio_data(positions, portfolio_value):
    """
    Build portfolio data dict for risk checks.
    
    Args:
        positions: List of current positions
        portfolio_value: Total portfolio value
        
    Returns:
        dict: Portfolio data for risk_guardian
    """
    # Calculate today's P&L (simplified - would need actual tracking)
    today_pnl = 0
    for pos in positions:
        if 'current_pnl' in pos:
            today_pnl += pos['current_pnl']
    
    return {
        'equity': portfolio_value,
        'positions': positions,
        'today_pnl': today_pnl,
        'week_pnl': None  # Would need historical tracking
    }


def get_sector_from_candidates(ticker, candidates):
    """
    Get sector for a ticker from candidates list.
    
    Args:
        ticker: Stock ticker
        candidates: List of candidate dicts
        
    Returns:
        str: Sector name or 'Unknown'
    """
    for candidate in candidates:
        if candidate['ticker'] == ticker:
            return candidate.get('sector', 'Unknown')
    return 'Unknown'


def save_daily_signals(result):
    """
    Save daily screening signals to file.
    
    Args:
        result: Result dict from run_daily_screening()
    """
    try:
        date_str = datetime.now().strftime('%Y%m%d')
        filename = DATA_DIR / f"daily_signals_{date_str}.json"
        
        with open(filename, 'w') as f:
            json.dump(result, f, indent=2)
        
        logger.info(f"Daily signals saved to {filename}")
        
    except Exception as e:
        logger.error(f"Error saving daily signals: {type(e).__name__}: {str(e)}")


def save_exit_signals(result):
    """
    Save exit signals to file.
    
    Args:
        result: Result dict from monitor_positions()
    """
    try:
        date_str = datetime.now().strftime('%Y%m%d')
        filename = DATA_DIR / f"exit_signals_{date_str}.json"
        
        # Append to file if it exists (multiple runs per day)
        if filename.exists():
            with open(filename, 'r') as f:
                existing_data = json.load(f)
            
            # Append new signals
            if 'runs' not in existing_data:
                existing_data = {'runs': [existing_data]}
            existing_data['runs'].append(result)
            
            with open(filename, 'w') as f:
                json.dump(existing_data, f, indent=2)
        else:
            with open(filename, 'w') as f:
                json.dump({'runs': [result]}, f, indent=2)
        
        logger.info(f"Exit signals saved to {filename}")
        
    except Exception as e:
        logger.error(f"Error saving exit signals: {type(e).__name__}: {str(e)}")


if __name__ == "__main__":
    import sys
    
    # Command-line interface
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python orchestrator.py screen [portfolio_value]  - Run daily screening")
        print("  python orchestrator.py monitor                    - Monitor positions")
        print("  python orchestrator.py status                     - Check market status")
        print("  python orchestrator.py watchdog                   - Check Llama health and optimize")
        print("  python orchestrator.py preload                    - Preload Llama models (run at 2:55 AM)")
        print("  python orchestrator.py tune                       - Auto-tune parameters")
        print("  python orchestrator.py review                     - Weekly performance review")
        print("  python orchestrator.py architect                  - Run meta-architect improvement cycle")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "screen":
        portfolio_value = float(sys.argv[2]) if len(sys.argv) > 2 else PORTFOLIO_VALUE
        print(f"\nRunning daily screening workflow (Portfolio: ${portfolio_value:,.2f})...")
        result = run_daily_screening(portfolio_value)
        
        print("\n" + "=" * 80)
        print("SCREENING RESULTS")
        print("=" * 80)
        print(f"Candidates found: {result['candidates_found']}")
        print(f"Approved trades: {len(result['approved_trades'])}")
        print(f"Rejected trades: {len(result['rejected_trades'])}")
        
        if result.get('executed_trades'):
            print("\nExecuted Trades:")
            for trade in result['executed_trades']:
                print(f"  {trade['ticker']}: {trade['shares']} shares @ ${trade['entry_price']:.2f} = ${trade['position_size']:.2f}")
                print(f"    Order ID: {trade['order_id']}")
                print(f"    Status: {trade['order_status']}")
                print(f"    Confidence: {trade['confidence']:.2f}")
                if trade.get('risk_adjusted'):
                    print(f"    (Position size adjusted by risk management)")
        
        if result.get('execution_failures'):
            print("\nExecution Failures:")
            for trade in result['execution_failures']:
                print(f"  {trade['ticker']}: {trade['execution_error']}")
        
        if result['rejected_trades']:
            print("\nRejected Trades:")
            for trade in result['rejected_trades']:
                print(f"  {trade['ticker']}: {trade['reason']}")
        
        print(f"\nRisk Status:")
        risk = result['risk_status']
        print(f"  Consecutive losses: {risk['consecutive_losses']}")
        print(f"  Position size reduction: {risk['position_size_reduction']*100:.0f}%")
        print(f"  Circuit breaker active: {risk['circuit_breaker_active']}")
        
    elif command == "monitor":
        print("\nMonitoring open positions...")
        result = monitor_positions()
        
        print("\n" + "=" * 80)
        print("POSITION MONITORING RESULTS")
        print("=" * 80)
        print(f"Market open: {result['market_open']}")
        print(f"Positions monitored: {result['positions_monitored']}")
        
        if result.get('executed_exits'):
            print(f"\nExecuted Exits:")
            for signal in result['executed_exits']:
                print(f"  {signal['ticker']}: {signal['action']}")
                print(f"    Order ID: {signal['order_id']}")
                print(f"    Status: {signal['order_status']}")
                print(f"    Reason: {signal['reason']}")
                if signal.get('current_price'):
                    print(f"    Current price: ${signal['current_price']:.2f}")
                if signal.get('pnl_pct') is not None:
                    print(f"    P&L: {signal['pnl_pct']*100:.2f}%")
                if signal.get('sell_qty', 0) > 0:
                    print(f"    Sold: {signal['sell_qty']} shares")
        
        if result.get('exit_failures'):
            print(f"\nExit Failures:")
            for signal in result['exit_failures']:
                print(f"  {signal['ticker']}: {signal['execution_error']}")
        
        if result.get('action_summary'):
            print(f"\nAction Summary: {result['action_summary']}")
    
    elif command == "status":
        print("\nChecking market status...")
        market_open = is_market_hours()
        et_tz = pytz.timezone('US/Eastern')
        now_et = datetime.now(et_tz)
        
        print(f"\nCurrent time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"Market open: {market_open}")
        print(f"Market hours: {MARKET_OPEN.strftime('%H:%M')} - {MARKET_CLOSE.strftime('%H:%M')} ET, Mon-Fri")
        
        if not market_open:
            if now_et.weekday() >= 5:
                print("Reason: Weekend")
            else:
                print(f"Reason: Outside market hours")
    
    elif command == "tune":
        from agents.performance_analyzer import auto_tune_parameters
        print("\nAuto-tuning parameters based on recent performance...")
        result = auto_tune_parameters()
        
        print("\n" + "=" * 80)
        print("AUTO-TUNING RESULTS")
        print("=" * 80)
        print(f"Tuned: {result['tuned']}")
        
        if result['tuned']:
            print(f"\nChanges made:")
            for change in result['changes_made']:
                print(f"  {change['parameter']}: {change['old_value']} → {change['new_value']}")
                print(f"    Reason: {change['reason']}")
        else:
            print(f"\nReason: {result.get('reason', 'No changes needed')}")
    
    elif command == "watchdog":
        print("\nRunning Llama watchdog...")
        report = run_watchdog()
        
        print("\n" + "=" * 80)
        print("LLAMA WATCHDOG REPORT")
        print("=" * 80)
        print(f"Health Score: {report['health']['health_score']}/100")
        print(f"Service Running: {report['health']['service_running']}")
        print(f"Emergency Mode: {report['emergency_mode']}")
        
        if report['health']['response_time']:
            print(f"Response Time: {report['health']['response_time']:.2f}s")
        
        if report['health']['models_loaded']:
            print(f"Models Loaded: {', '.join(report['health']['models_loaded'])}")
        
        if report['health']['issues']:
            print("\nIssues Detected:")
            for issue in report['health']['issues']:
                print(f"  - {issue}")
        
        if report['optimization']['optimized']:
            print("\nOptimizations Applied:")
            for action in report['optimization']['actions_taken']:
                print(f"  - {action}")
    
    elif command == "preload":
        print("\nPreloading Llama models...")
        result = preload_models()
        
        print("\n" + "=" * 80)
        print("LLAMA PRELOAD")
        print("=" * 80)
        print(f"Success: {result['success']}")
        
        if result['success']:
            print(f"Preload Time: {result['preload_time']:.2f}s")
            print("Models ready for 3 AM screening")
        else:
            print(f"Error: {result['error']}")
    
    elif command == "review":
        from agents.performance_analyzer import weekly_review
        print("\nGenerating weekly performance review...")
        report = weekly_review()
        
        print("\n" + "=" * 80)
        print("WEEKLY REVIEW")
        print("=" * 80)
        print(f"Week ending: {report['week_ending']}")
        print(f"Trades: {report.get('trades_analyzed', 0)}")
        
        if report.get('trades_analyzed', 0) > 0:
            print(f"Win rate: {report['win_rate']*100:.1f}%")
            print(f"Average win: {report['avg_win_pct']:.2f}%")
            print(f"Average loss: {report['avg_loss_pct']:.2f}%")
    
    elif command == "architect":
        from agents.meta_architect import autonomous_improvement_cycle
        print("\nRunning Meta-Architect improvement cycle...")
        result = autonomous_improvement_cycle()
        
        print("\n" + "=" * 80)
        print("META-ARCHITECT RESULTS")
        print("=" * 80)
        print(f"Success: {result['success']}")
        
        if result.get('error'):
            print(f"Error: {result['error']}")
        else:
            print(f"Agents created: {result.get('total_created', 0)}")
            print(f"Agents failed: {result.get('total_failed', 0)}")
            
            if result.get('agents_created'):
                print("\n✓ Successfully Created Agents:")
                for agent in result['agents_created']:
                    print(f"\n  {agent['agent_name']}")
                    print(f"    Improvement: {agent['improvement']*100:.1f}%")
                    print(f"    Win rate: {agent['baseline_win_rate']*100:.1f}% → {agent['agent_win_rate']*100:.1f}%")
                    print(f"    Addresses: {agent['weakness_addressed']}")
            
            if result.get('agents_failed'):
                print(f"\n✗ Failed Agents: {len(result['agents_failed'])}")
                for agent in result['agents_failed']:
                    print(f"  - {agent['agent_name']}: {agent.get('reason', agent.get('error', 'Unknown'))}")
    
    else:
        print(f"Unknown command: {command}")
        print("Use 'screen', 'monitor', 'status', 'watchdog', 'preload', 'tune', or 'review'")
        sys.exit(1)
