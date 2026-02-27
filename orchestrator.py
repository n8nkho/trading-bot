"""
Trading System Orchestrator
Coordinates the complete workflow: screening, entry evaluation, risk management, and position monitoring
"""

import asyncio
import json
import logging
import os
from datetime import datetime, time
from dateutil import parser
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
# from agents.fortress_orchestrator import fortress_daily_check, generate_fortress_report
from agents.document_analyst import quick_fundamental_check
from agents.intraday_sniper import scan_intraday_opportunities
from utils.grok_sentiment import check_twitter_sentiment
from utils.cost_calculator import (
    get_daily_costs,
    get_monthly_projection,
    get_lifetime_costs,
    get_cost_per_trade,
    generate_cost_report
)

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

# Auto-execution configuration (Paper Trading Only)
PAPER_TRADING_AUTO_EXECUTE = True  # Auto-execute qualified trades
MAX_AUTO_TRADES_PER_DAY = 3
MIN_CONFIDENCE_FOR_AUTO = 0.70
AUTO_POSITION_SIZE = 500  # $500 per trade
AUTO_STOP_LOSS_PCT = 5.0  # 5% stop loss
AUTO_PROFIT_TARGET_PCT = 10.0  # 10% profit target

# Market hours (Eastern Time)
MARKET_OPEN = time(9, 30)   # 9:30 AM ET
MARKET_CLOSE = time(16, 0)  # 4:00 PM ET

# Screening configuration
GROK_CONFIDENCE_THRESHOLD = 0.8  # Only use Grok for high-confidence candidates
VISION_CONFIDENCE_THRESHOLD = 0.9  # Only use Vision for very high-confidence candidates
FUNDAMENTAL_CONFIDENCE_THRESHOLD = 0.85  # Only use fundamental analysis for high-confidence candidates
FUNDAMENTAL_RISK_THRESHOLD = 70  # Skip if SEC risk score >= 70

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


def format_option_symbol(ticker, expiration, strike, call=True):
    """
    Format an option symbol in OCC format for Alpaca.

    Args:
        ticker (str): Stock ticker symbol.
        expiration (str): Expiration date in "YYYY-MM-DD" format.
        strike (float): Strike price.
        call (bool): True for call option, False for put option.

    Returns:
        str: Formatted option symbol.
    """
    # Parse expiration date
    exp_date = parser.parse(expiration)
    exp_str = exp_date.strftime('%y%m%d')

    # Determine option type
    option_type = 'C' if call else 'P'

    # Format strike price
    strike_str = f"{int(strike * 1000):08d}"

    # Construct OCC option symbol
    return f"{ticker.upper()}{exp_str}{option_type}{strike_str}"


async def run_daily_screening_async(portfolio_value=PORTFOLIO_VALUE):
    """
    Run the complete daily screening workflow with async parallel execution.
    
    Workflow:
    1. Run screener to find beaten-down stocks
    2. For high-confidence candidates, run parallel checks:
       - Grok sentiment analysis
       - Vision chart analysis
       - SEC fundamental analysis
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
        
        # Step 2: Run parallel analysis for high-confidence candidates
        logger.info("Step 2: Running parallel analysis (Grok, Vision, Fundamentals)...")
        
        # Create async tasks for each candidate
        async def analyze_candidate(candidate):
            """Run all applicable analyses for a candidate in parallel."""
            confidence = candidate.get('analysis', {}).get('confidence', 0)
            ticker = candidate['ticker']
            
            # Determine which analyses to run
            tasks = []
            task_names = []
            
            # Grok sentiment (if confidence >= threshold)
            if confidence >= GROK_CONFIDENCE_THRESHOLD:
                tasks.append(asyncio.to_thread(check_twitter_sentiment, ticker, confidence))
                task_names.append('grok')
            else:
                tasks.append(asyncio.sleep(0, result=None))  # Dummy task
                task_names.append('grok')
            
            # Fundamental analysis (if confidence >= threshold)
            if confidence >= FUNDAMENTAL_CONFIDENCE_THRESHOLD:
                tasks.append(asyncio.to_thread(quick_fundamental_check, ticker, confidence))
                task_names.append('fundamental')
            else:
                tasks.append(asyncio.sleep(0, result=None))  # Dummy task
                task_names.append('fundamental')
            
            # Run all tasks in parallel
            logger.info(f"{ticker}: Starting parallel analysis (confidence: {confidence:.2f})...")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            grok_result = results[0] if not isinstance(results[0], Exception) else None
            fundamental_result = results[1] if not isinstance(results[1], Exception) else None
            
            # Handle Grok sentiment
            if confidence >= GROK_CONFIDENCE_THRESHOLD:
                if isinstance(results[0], Exception):
                    logger.error(f"{ticker}: Grok analysis failed: {results[0]}")
                    candidate['grok_sentiment'] = None
                else:
                    candidate['grok_sentiment'] = grok_result
                    if grok_result:
                        logger.info(f"{ticker}: Grok sentiment = {grok_result}")
                        
                        # Adjust confidence based on sentiment
                        if grok_result == "BEARISH":
                            original_confidence = confidence
                            candidate['analysis']['confidence'] = confidence * 0.7
                            logger.warning(f"{ticker}: Confidence reduced from {original_confidence:.2f} to {confidence*0.7:.2f} due to bearish sentiment")
                        elif grok_result == "BULLISH":
                            original_confidence = confidence
                            candidate['analysis']['confidence'] = min(confidence * 1.1, 1.0)
                            logger.info(f"{ticker}: Confidence increased from {original_confidence:.2f} to {min(confidence*1.1, 1.0):.2f} due to bullish sentiment")
            else:
                candidate['grok_sentiment'] = None
            
            # Vision analysis is now handled in screener_agent.py
            # The vision_signal is already in the candidate dict
            candidate['vision_analysis'] = candidate.get('vision_signal')
            
            # Handle Fundamental analysis
            if confidence >= FUNDAMENTAL_CONFIDENCE_THRESHOLD:
                if isinstance(results[2], Exception):
                    logger.error(f"{ticker}: Fundamental analysis failed: {results[2]}")
                    candidate['fundamental_analysis'] = None
                else:
                    candidate['fundamental_analysis'] = fundamental_result
                    
                    # Check risk score threshold
                    risk_score = fundamental_result.get('risk_score')
                    
                    if risk_score is not None and risk_score >= FUNDAMENTAL_RISK_THRESHOLD:
                        # High risk detected - reduce confidence significantly
                        original_confidence = candidate['analysis']['confidence']
                        candidate['analysis']['confidence'] = original_confidence * 0.5
                        logger.warning(f"{ticker}: HIGH RISK fundamentals (score: {risk_score}) - Confidence: {original_confidence:.2f} → {original_confidence*0.5:.2f}")
                        logger.warning(f"{ticker}: {fundamental_result['reason']}")
                    elif fundamental_result['fundamental_approved']:
                        logger.info(f"{ticker}: Fundamentals OK - {fundamental_result['reason']}")
                    else:
                        # Some concern but not critical
                        original_confidence = candidate['analysis']['confidence']
                        candidate['analysis']['confidence'] = fundamental_result['adjusted_confidence']
                        logger.info(f"{ticker}: Fundamental check: {fundamental_result['reason']}")
                        if original_confidence != fundamental_result['adjusted_confidence']:
                            logger.info(f"{ticker}: Confidence: {original_confidence:.2f} → {fundamental_result['adjusted_confidence']:.2f}")
            else:
                candidate['fundamental_analysis'] = None
            
            logger.info(f"{ticker}: Parallel analysis complete")
            return candidate
        
        # Run analysis for all candidates in parallel
        analyzed_candidates = await asyncio.gather(*[analyze_candidate(c) for c in candidates])
        
        # Calculate total costs
        fundamental_total_cost = sum(
            c.get('fundamental_analysis', {}).get('cost', 0) 
            for c in analyzed_candidates 
            if c.get('fundamental_analysis')
        )
        
        if fundamental_total_cost > 0:
            logger.info(f"Total fundamental analysis cost: ${fundamental_total_cost:.3f}")
        
        # Update candidates with analyzed results
        candidates = analyzed_candidates
        
        # Step 2.5: Auto-execute qualified trades (if enabled)
        auto_execution_result = None
        if PAPER_TRADING_AUTO_EXECUTE:
            logger.info("Step 2.5: Auto-executing qualified trades...")
            auto_execution_result = await execute_auto_trades(candidates, portfolio_value)
            
            if auto_execution_result['executed']:
                logger.info(f"Auto-executed {len(auto_execution_result['executed'])} trades")
                for trade in auto_execution_result['executed']:
                    logger.info(f"  ✓ {trade['ticker']}: {trade['shares']} shares @ ${trade['entry_price']:.2f}")
            
            if auto_execution_result['skipped']:
                logger.info(f"Skipped {len(auto_execution_result['skipped'])} candidates")
        
        # Step 3: Evaluate entry timing and conditions
        logger.info("Step 3: Evaluating entry conditions...")
        entry_decisions = await asyncio.to_thread(evaluate_entry, candidates, portfolio_value)
        
        buy_decisions = [d for d in entry_decisions if d['action'] == 'BUY']
        skip_decisions = [d for d in entry_decisions if d['action'] == 'SKIP']
        
        logger.info(f"Entry evaluation: {len(buy_decisions)} BUY, {len(skip_decisions)} SKIP")
        
        # Step 4: Check account and risk limits
        logger.info("Step 4: Checking account status and risk limits...")
        
        # Get account info (async)
        account_info = await asyncio.to_thread(get_account_info)
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
            
            # Check risk limits (async)
            risk_check = await asyncio.to_thread(check_risk_limits, portfolio_data, new_position)
            
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
                    'vision_analysis': decision.get('vision_analysis'),
                    'fundamental_analysis': decision.get('fundamental_analysis'),
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
        
        # Step 5: Execute approved trades (in parallel)
        logger.info("Step 5: Executing approved trades...")
        
        async def execute_trade(trade):
            """Execute a single trade asynchronously."""
            if trade.get('type') == 'OPTION':
                ticker = trade['ticker']
                strike = trade['strike']
                expiration = trade['expiration']
                contracts = trade['contracts']
                call = trade.get('call', True)

                # Format option symbol
                option_symbol = format_option_symbol(ticker, expiration, strike, call)
                logger.info(f"Executing OPTION order: {option_symbol} x {contracts} contracts")

                # Submit option order (pseudo-code, replace with actual Alpaca API call)
                # order_result = await asyncio.to_thread(submit_option_order, option_symbol, contracts)

                # Simulate order result for demonstration
                order_result = {'success': True, 'order_id': '12345', 'status': 'filled', 'filled_qty': contracts, 'filled_price': strike}

            else:
                ticker = trade['ticker']
                shares = trade['shares']
                entry_price = trade['entry_price']
                logger.info(f"Executing STOCK order: {ticker} x {shares} shares")

                # Execute buy order
                order_result = await asyncio.to_thread(execute_buy_order, ticker, shares, entry_price)

            if order_result['success']:
                logger.info(f"{ticker}: Order executed successfully - ID: {order_result['order_id']}")
                
                # Add order info to trade
                trade['order_id'] = order_result['order_id']
                trade['order_status'] = order_result['status']
                trade['filled_qty'] = order_result['filled_qty']
                trade['filled_price'] = order_result['filled_price']
                trade['executed'] = True
                trade['execution_time'] = datetime.now().isoformat()
                
                # Add to positions file
                await asyncio.to_thread(add_position, {
                    'ticker': ticker,
                    'shares': trade.get('shares', 0),
                    'entry_price': trade.get('entry_price', 0),
                    'entry_date': datetime.now().isoformat(),
                    'order_id': order_result['order_id'],
                    'sector': get_sector_from_candidates(ticker, candidates),
                    'stop_loss_pct': current_params['stop_loss_pct'],
                    'take_profit_pct': current_params.get('take_profit_pct', 15.0)
                })
                
                return ('success', trade)
            else:
                logger.error(f"{ticker}: Order execution failed - {order_result['error']}")
                trade['executed'] = False
                trade['execution_error'] = order_result['error']
                return ('failure', trade)
        
        # Execute all trades in parallel
        execution_results = await asyncio.gather(*[execute_trade(t) for t in approved_trades])
        
        executed_trades = [trade for status, trade in execution_results if status == 'success']
        execution_failures = [trade for status, trade in execution_results if status == 'failure']
        
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
            'auto_execution': auto_execution_result,
            'risk_status': get_risk_status(),
            'portfolio_value': portfolio_value,
            'account_info': account_info,
            'fundamental_cost': fundamental_total_cost
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


def run_fortress():
    """Run complete fortress hedging system."""
    from agents.fortress_orchestrator import fortress_daily_check
    
    logger.info("=" * 80)
    logger.info("FORTRESS HEDGING SYSTEM")
    logger.info("=" * 80)
    
    try:
        result = fortress_daily_check()
        
        if result:
            logger.info("Fortress check complete")
            logger.info(f"Market regime: {result.get('market_conditions', {}).get('regime', 'N/A')}")
            logger.info(f"Strategies evaluated: {len(result.get('recommendations', {}))}")
        
        return result
    except Exception as e:
        logger.error(f"Fortress error: {e}")
        return None


def run_daily_screening(portfolio_value=PORTFOLIO_VALUE):
    """
    Synchronous wrapper for async run_daily_screening_async().
    
    Args:
        portfolio_value: Current portfolio value for position sizing
        
    Returns:
        dict: Screening results
    """
    return asyncio.run(run_daily_screening_async(portfolio_value))


def run_fortress():
    """Run complete fortress hedging system."""
    logger.info("=" * 80)
    logger.info("FORTRESS HEDGING SYSTEM")
    logger.info("=" * 80)
    
    try:
        # Run daily check
        result = fortress_daily_check()
        
        if result:
            logger.info("Fortress check complete")
            logger.info(f"Market regime: {result.get('market_conditions', {}).get('regime', 'N/A')}")
            logger.info(f"Strategies evaluated: {len(result.get('recommendations', {}))}")
            
            # Show recommendations
            recs = result.get('recommendations', {})
            for strategy, data in recs.items():
                if data:
                    logger.info(f"{strategy}: {data}")
        
        return result
        
    except Exception as e:
        logger.error(f"Fortress error: {e}")
        import traceback
        traceback.print_exc()
        run_fortress()

async def monitor_positions_async():
    """
    Monitor open positions and generate exit signals (async version).
    
    Workflow:
    1. Load open positions from data/positions.json
    2. Check if market is open
    3. Run exit monitoring for each position in parallel
    4. Execute exit orders in parallel
    5. Save exit signals to data/exit_signals_YYYYMMDD.json
    
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
        
        # Run exit monitoring (async)
        exit_signals = await asyncio.to_thread(monitor_exit_conditions, positions)
        
        # Count actions
        action_counts = {}
        for signal in exit_signals:
            action = signal['action']
            action_counts[action] = action_counts.get(action, 0) + 1
        
        logger.info(f"Exit monitoring complete: {action_counts}")
        
        # Execute sell orders for exit signals (in parallel)
        logger.info("Executing exit orders...")
        
        async def execute_exit(signal):
            """Execute a single exit order asynchronously."""
            if signal['action'] not in ['SELL_ALL', 'SELL_HALF']:
                return None
            
            ticker = signal['ticker']
            sell_qty = signal.get('sell_qty', 0)
            
            if sell_qty <= 0:
                return None
            
            # Execute sell order
            order_result = await asyncio.to_thread(execute_sell_order, ticker, sell_qty)
            
            if order_result['success']:
                logger.info(f"{ticker}: Exit order executed - ID: {order_result['order_id']}")
                
                signal['order_id'] = order_result['order_id']
                signal['order_status'] = order_result['status']
                signal['filled_qty'] = order_result['filled_qty']
                signal['filled_price'] = order_result['filled_price']
                signal['executed'] = True
                signal['execution_time'] = datetime.now().isoformat()
                
                # Update positions file
                if signal['action'] == 'SELL_ALL':
                    await asyncio.to_thread(remove_position, ticker)
                else:  # SELL_HALF
                    await asyncio.to_thread(update_position_quantity, ticker, sell_qty)
                
                return ('success', signal)
            else:
                logger.error(f"{ticker}: Exit order failed - {order_result['error']}")
                signal['executed'] = False
                signal['execution_error'] = order_result['error']
                return ('failure', signal)
        
        # Execute all exits in parallel
        exit_results = await asyncio.gather(*[execute_exit(s) for s in exit_signals])
        
        executed_exits = [signal for result in exit_results if result and result[0] == 'success' for _, signal in [result]]
        exit_failures = [signal for result in exit_results if result and result[0] == 'failure' for _, signal in [result]]
        
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


def monitor_positions():
    """
    Synchronous wrapper for async monitor_positions_async().
    
    Returns:
        dict: Position monitoring results
    """
    return asyncio.run(monitor_positions_async())


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
            positions = json.load(f)
        
        # Handle both list format and dict format for backwards compatibility
        if isinstance(positions, dict):
            positions = positions.get('positions', [])
        
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
        
        # Save back to file as a list
        with open(POSITIONS_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
        
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
        
        # Save back to file as a list
        with open(POSITIONS_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
        
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
                # Handle both 'shares' and 'qty' keys
                old_qty = pos.get('shares') or pos.get('qty', 0)
                new_qty = old_qty - qty_sold
                
                # Update both keys if they exist
                if 'shares' in pos:
                    pos['shares'] = new_qty
                if 'qty' in pos:
                    pos['qty'] = new_qty
                
                logger.info(f"Updated position: {ticker} - {old_qty} -> {new_qty} shares")
                break
        
        # Save back to file as a list
        with open(POSITIONS_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
        
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


def get_auto_trades_today():
    """
    Get count of auto-executed trades today.
    
    Returns:
        int: Number of auto-trades executed today
    """
    try:
        date_str = datetime.now().strftime('%Y%m%d')
        filename = DATA_DIR / f"auto_trades_{date_str}.json"
        
        if not filename.exists():
            return 0
        
        with open(filename, 'r') as f:
            data = json.load(f)
        
        return len(data.get('trades', []))
        
    except Exception as e:
        logger.error(f"Error getting auto-trades count: {type(e).__name__}: {str(e)}")
        return 0


def log_auto_trade(trade_data):
    """
    Log auto-executed trade to daily file and decisions log.
    
    Args:
        trade_data: Dict with trade details
    """
    try:
        date_str = datetime.now().strftime('%Y%m%d')
        filename = DATA_DIR / f"auto_trades_{date_str}.json"
        
        # Load existing trades
        if filename.exists():
            with open(filename, 'r') as f:
                data = json.load(f)
        else:
            data = {'date': date_str, 'trades': []}
        
        # Add new trade
        data['trades'].append(trade_data)
        
        # Save to file
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Also log to decisions_log.jsonl
        decisions_log = DATA_DIR / "decisions_log.jsonl"
        with open(decisions_log, 'a') as f:
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'type': 'AUTO_TRADE',
                'ticker': trade_data['ticker'],
                'action': 'BUY',
                'shares': trade_data['shares'],
                'entry_price': trade_data['entry_price'],
                'position_size': trade_data['position_size'],
                'stop_loss': trade_data['stop_loss'],
                'profit_target': trade_data['profit_target'],
                'confidence': trade_data['confidence'],
                'reasoning': trade_data['reasoning']
            }
            f.write(json.dumps(log_entry) + '\n')
        
        logger.info(f"Auto-trade logged: {trade_data['ticker']}")
        
    except Exception as e:
        logger.error(f"Error logging auto-trade: {type(e).__name__}: {str(e)}")


async def execute_auto_trades(candidates, portfolio_value):
    """
    Auto-execute qualified trades in paper trading mode.
    
    Args:
        candidates: List of analyzed candidates
        portfolio_value: Current portfolio value
        
    Returns:
        dict: {
            'executed': list of executed trades,
            'skipped': list of skipped trades with reasons
        }
    """
    logger.info("=" * 80)
    logger.info("AUTO-EXECUTION MODE (PAPER TRADING)")
    logger.info("=" * 80)
    
    # Safety check
    if not PAPER_TRADING_AUTO_EXECUTE:
        logger.info("Auto-execution disabled - candidates found but not executed")
        return {'executed': [], 'skipped': []}
    
    if not alpaca_client:
        logger.error("Cannot auto-execute - Alpaca client not initialized")
        return {'executed': [], 'skipped': []}
    
    # Check daily limit
    auto_trades_today = get_auto_trades_today()
    if auto_trades_today >= MAX_AUTO_TRADES_PER_DAY:
        logger.warning(f"Daily auto-trade limit reached: {auto_trades_today}/{MAX_AUTO_TRADES_PER_DAY}")
        return {'executed': [], 'skipped': []}
    
    # Load current positions
    current_positions = load_positions()
    held_tickers = {pos['ticker'] for pos in current_positions}
    
    # Filter candidates for auto-execution
    qualified = []
    skipped = []
    
    for candidate in candidates:
        ticker = candidate['ticker']
        confidence = candidate.get('analysis', {}).get('confidence', 0)
        current_price = candidate.get('current_price', 0)
        
        # Check confidence threshold
        if confidence < MIN_CONFIDENCE_FOR_AUTO:
            skipped.append({
                'ticker': ticker,
                'reason': f'Confidence {confidence:.2f} < {MIN_CONFIDENCE_FOR_AUTO}',
                'confidence': confidence
            })
            continue
        
        # Check if already holding
        if ticker in held_tickers:
            skipped.append({
                'ticker': ticker,
                'reason': 'Already holding position',
                'confidence': confidence
            })
            continue
        
        # Check if we have price data
        if not current_price or current_price <= 0:
            skipped.append({
                'ticker': ticker,
                'reason': 'No valid price data',
                'confidence': confidence
            })
            continue
        
        # Check daily limit
        if len(qualified) + auto_trades_today >= MAX_AUTO_TRADES_PER_DAY:
            skipped.append({
                'ticker': ticker,
                'reason': f'Daily limit ({MAX_AUTO_TRADES_PER_DAY}) would be exceeded',
                'confidence': confidence
            })
            continue
        
        qualified.append(candidate)
    
    logger.info(f"Qualified for auto-execution: {len(qualified)}")
    logger.info(f"Skipped: {len(skipped)}")
    
    if len(qualified) == 0:
        return {'executed': [], 'skipped': skipped}
    
    # Execute qualified trades
    executed = []
    
    for candidate in qualified:
        ticker = candidate['ticker']
        current_price = candidate['current_price']
        confidence = candidate.get('analysis', {}).get('confidence', 0)
        reasoning = candidate.get('analysis', {}).get('reasoning', 'No reasoning provided')
        
        # Calculate position size
        shares = int(AUTO_POSITION_SIZE / current_price)
        if shares <= 0:
            logger.warning(f"{ticker}: Cannot buy fractional shares (price: ${current_price:.2f})")
            skipped.append({
                'ticker': ticker,
                'reason': 'Price too high for position size',
                'confidence': confidence
            })
            continue
        
        position_size = shares * current_price
        
        # Calculate stop loss and profit target
        stop_loss_price = current_price * (1 - AUTO_STOP_LOSS_PCT / 100)
        profit_target_price = current_price * (1 + AUTO_PROFIT_TARGET_PCT / 100)
        
        logger.info("=" * 80)
        logger.info(f"AUTO-EXECUTING: {ticker} at ${current_price:.2f}, {shares} shares")
        logger.info(f"Position Size: ${position_size:.2f}")
        logger.info(f"Stop Loss: ${stop_loss_price:.2f} (-{AUTO_STOP_LOSS_PCT}%)")
        logger.info(f"Profit Target: ${profit_target_price:.2f} (+{AUTO_PROFIT_TARGET_PCT}%)")
        logger.info(f"Confidence: {confidence:.2f}")
        logger.info(f"Reason: {reasoning}")
        logger.info("=" * 80)
        
        # Execute buy order
        order_result = await asyncio.to_thread(execute_buy_order, ticker, shares, current_price)
        
        if order_result['success']:
            logger.info(f"{ticker}: ✓ AUTO-TRADE EXECUTED - Order ID: {order_result['order_id']}")
            
            # Prepare trade data
            trade_data = {
                'ticker': ticker,
                'shares': shares,
                'entry_price': current_price,
                'position_size': position_size,
                'stop_loss': stop_loss_price,
                'profit_target': profit_target_price,
                'confidence': confidence,
                'reasoning': reasoning,
                'order_id': order_result['order_id'],
                'order_status': order_result['status'],
                'filled_qty': order_result['filled_qty'],
                'filled_price': order_result['filled_price'],
                'timestamp': datetime.now().isoformat(),
                'grok_sentiment': candidate.get('grok_sentiment'),
                'vision_analysis': candidate.get('vision_analysis'),
                'fundamental_analysis': candidate.get('fundamental_analysis')
            }
            
            # Log trade
            await asyncio.to_thread(log_auto_trade, trade_data)
            
            # Add to positions
            await asyncio.to_thread(add_position, {
                'ticker': ticker,
                'shares': shares,
                'entry_price': current_price,
                'entry_date': datetime.now().isoformat(),
                'order_id': order_result['order_id'],
                'sector': get_sector_from_candidates(ticker, candidates),
                'stop_loss_pct': AUTO_STOP_LOSS_PCT,
                'take_profit_pct': AUTO_PROFIT_TARGET_PCT,
                'auto_executed': True
            })
            
            executed.append(trade_data)
            
        else:
            logger.error(f"{ticker}: ✗ AUTO-TRADE FAILED - {order_result['error']}")
            skipped.append({
                'ticker': ticker,
                'reason': f"Execution failed: {order_result['error']}",
                'confidence': confidence
            })
    
    logger.info("=" * 80)
    logger.info(f"AUTO-EXECUTION COMPLETE: {len(executed)} executed, {len(skipped)} skipped")
    logger.info("=" * 80)
    
    return {'executed': executed, 'skipped': skipped}


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
        print("  python orchestrator.py costs                      - Show comprehensive cost report")
        print("  python orchestrator.py watchdog                   - Check Llama health and optimize")
        print("  python orchestrator.py preload                    - Preload Llama models (run at 2:55 AM)")
        print("  python orchestrator.py tune                       - Auto-tune parameters")
        print("  python orchestrator.py review                     - Weekly performance review")
        print("  python orchestrator.py architect                  - Run meta-architect improvement cycle")
        print("  python orchestrator.py fortress                   - Run complete hedging system")
        print("  python orchestrator.py snipe [portfolio_value]    - Run intraday sniper for quick trades")
        print("  python orchestrator.py snipe [portfolio_value]    - Run intraday sniper for quick trades")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "screen":
        portfolio_value = float(sys.argv[2]) if len(sys.argv) > 2 else PORTFOLIO_VALUE
        print(f"\nRunning daily screening workflow (Portfolio: ${portfolio_value:,.2f})...")
        print("Using async parallel execution for 5x faster analysis...")
        result = run_daily_screening(portfolio_value)
        
        print("\n" + "=" * 80)
        print("SCREENING RESULTS")
        print("=" * 80)
        print(f"Candidates found: {result['candidates_found']}")
        
        # Show auto-execution results
        if result.get('auto_execution'):
            auto_exec = result['auto_execution']
            print(f"\nAuto-Execution (Paper Trading):")
            print(f"  Executed: {len(auto_exec['executed'])}")
            print(f"  Skipped: {len(auto_exec['skipped'])}")
            
            if auto_exec['executed']:
                print("\n  ✓ Auto-Executed Trades:")
                for trade in auto_exec['executed']:
                    print(f"    {trade['ticker']}: {trade['shares']} shares @ ${trade['entry_price']:.2f}")
                    print(f"      Stop: ${trade['stop_loss']:.2f}, Target: ${trade['profit_target']:.2f}")
                    print(f"      Confidence: {trade['confidence']:.2f}")
                    print(f"      Order ID: {trade['order_id']}")
        
        print(f"\nApproved trades: {len(result['approved_trades'])}")
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
        print("Using async parallel execution for faster order processing...")
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
    
    elif command == "fortress":
        run_fortress()
    elif command == "costs":
        # ANSI color codes for colorful output
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        BLUE = '\033[94m'
        CYAN = '\033[96m'
        MAGENTA = '\033[95m'
        RED = '\033[91m'
        BOLD = '\033[1m'
        RESET = '\033[0m'
        
        print(f"\n{CYAN}{'=' * 80}{RESET}")
        print(f"{BOLD}{MAGENTA}💰 COMPREHENSIVE COST ANALYSIS{RESET}")
        print(f"{CYAN}{'=' * 80}{RESET}\n")
        
        # Get cost data
        today_costs = get_daily_costs()
        monthly = get_monthly_projection()
        lifetime = get_lifetime_costs()
        cost_per_trade = get_cost_per_trade()
        
        # TODAY'S COSTS
        print(f"{BOLD}{BLUE}📅 TODAY:{RESET}")
        print(f"  API Calls: {YELLOW}{today_costs['api_calls']}{RESET}")
        
        if today_costs['service_breakdown']:
            for service, data in today_costs['service_breakdown'].items():
                service_name = service.capitalize()
                if service == 'ollama':
                    print(f"  {GREEN}✓{RESET} {service_name}: {GREEN}$0.00 (FREE){RESET} ({data['calls']} calls)")
                else:
                    cost_color = GREEN if data['cost'] < 0.10 else YELLOW if data['cost'] < 1.0 else RED
                    print(f"  • {service_name}: {cost_color}${data['cost']:.4f}{RESET} ({data['calls']} calls)")
                    if data['savings'] > 0:
                        savings_pct = (data['savings'] / (data['cost'] + data['savings'])) * 100
                        print(f"    {CYAN}↓ Cache savings: ${data['savings']:.4f} ({savings_pct:.0f}%){RESET}")
        
        if today_costs['api_savings'] > 0:
            total_before = today_costs['api_cost'] + today_costs['api_savings']
            cache_pct = (today_costs['api_savings'] / total_before) * 100
            print(f"  {CYAN}💾 Total cache savings: ${today_costs['api_savings']:.4f} ({cache_pct:.0f}%){RESET}")
        
        print(f"  {GREEN}☁️  OCI Infrastructure: $0.00 (FREE tier){RESET}")
        
        total_color = GREEN if today_costs['total_cost'] < 0.50 else YELLOW if today_costs['total_cost'] < 2.0 else RED
        print(f"  {BOLD}TOTAL TODAY: {total_color}${today_costs['total_cost']:.4f}{RESET}\n")
        
        # MONTHLY PROJECTION
        print(f"{BOLD}{BLUE}📊 MONTHLY PROJECTION:{RESET}")
        print(f"  Daily Average: {YELLOW}${monthly.get('daily_average', 0):.4f}{RESET}")
        print(f"  API (projected): {YELLOW}${monthly.get('api_projection', 0):.2f}/month{RESET}")
        print(f"  OCI: {GREEN}$0.00/month (FREE){RESET}")
        
        monthly_projection = monthly.get('monthly_projection', 0)
        monthly_color = GREEN if monthly_projection < 10 else YELLOW if monthly_projection < 50 else RED
        print(f"  {BOLD}TOTAL: {monthly_color}${monthly_projection:.2f}/month{RESET}")
        
        days_sampled = monthly.get('days_sampled', 1)
        if days_sampled > 0:
            print(f"  {CYAN}(based on {days_sampled} day average){RESET}\n")
        else:
            print(f"  {CYAN}(no data available yet){RESET}\n")
        
        # LIFETIME STATS
        print(f"{BOLD}{BLUE}📈 LIFETIME STATISTICS:{RESET}")
        print(f"  Total Spent: {YELLOW}${lifetime.get('total_spent', 0):.2f}{RESET}")
        print(f"  Total Saved: {CYAN}${lifetime.get('total_saved', 0):.2f}{RESET} (via caching)")
        
        total_saved = lifetime.get('total_saved', 0)
        if total_saved > 0:
            roi_percent = lifetime.get('roi_percent', 0)
            roi_color = GREEN if roi_percent > 50 else YELLOW if roi_percent > 20 else RED
            print(f"  {BOLD}ROI from Caching: {roi_color}{roi_percent:.1f}%{RESET}")
        
        if cost_per_trade > 0:
            cpt_color = GREEN if cost_per_trade < 0.10 else YELLOW if cost_per_trade < 0.50 else RED
            print(f"  Cost per Trade: {cpt_color}${cost_per_trade:.4f}{RESET}")
        
        print(f"  Total API Calls: {YELLOW}{lifetime.get('total_calls', 0):,}{RESET}")
        print(f"  Days Active: {CYAN}{lifetime.get('days_active', 0)}{RESET}")
        
        first_call = lifetime.get('first_call')
        last_call = lifetime.get('last_call')
        if first_call and last_call:
            first_date = datetime.fromisoformat(first_call).strftime('%Y-%m-%d')
            last_date = datetime.fromisoformat(last_call).strftime('%Y-%m-%d')
            print(f"  Period: {CYAN}{first_date} → {last_date}{RESET}\n")
        
        # COST EFFICIENCY INSIGHTS
        print(f"{BOLD}{BLUE}💡 INSIGHTS:{RESET}")
        
        roi_percent = lifetime.get('roi_percent', 0)
        if roi_percent > 50:
            print(f"  {GREEN}✓ Excellent caching efficiency!{RESET}")
        elif roi_percent > 20:
            print(f"  {YELLOW}• Good caching performance{RESET}")
        else:
            print(f"  {RED}⚠ Consider optimizing cache usage{RESET}")
        
        monthly_projection = monthly.get('monthly_projection', 0)
        if monthly_projection < 10:
            print(f"  {GREEN}✓ Very low monthly costs (<$10){RESET}")
        elif monthly_projection < 50:
            print(f"  {YELLOW}• Moderate monthly costs ($10-$50){RESET}")
        else:
            print(f"  {RED}⚠ High monthly costs (>${monthly_projection:.0f}){RESET}")
        
        if cost_per_trade > 0 and cost_per_trade < 0.10:
            print(f"  {GREEN}✓ Excellent cost per trade (<$0.10){RESET}")
        elif cost_per_trade > 0 and cost_per_trade < 0.50:
            print(f"  {YELLOW}• Reasonable cost per trade ($0.10-$0.50){RESET}")
        elif cost_per_trade > 0:
            print(f"  {RED}⚠ High cost per trade (>${cost_per_trade:.2f}){RESET}")
        
        print(f"  {GREEN}✓ OCI infrastructure: 100% FREE (A1.Flex ARM){RESET}")
        
        print(f"\n{CYAN}{'=' * 80}{RESET}\n")
    
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
    

    elif command == "fortress":
        print("\nRunning complete fortress hedging system...")
        result = run_fortress()
        
        print("\n" + "=" * 80)
        print("FORTRESS HEDGING SYSTEM RESULTS")
        print("=" * 80)
        if result:
            print(f"Market regime: {result.get('market_conditions', {}).get('regime', 'N/A')}")
            print(f"Strategies evaluated: {len(result.get('recommendations', {}))}")
            for strategy, data in result.get('recommendations', {}).items():
                if data:
                    print(f"{strategy}: {data}")
        else:
            print("No results returned from fortress hedging system.")
    elif command == "snipe":
        portfolio_value = float(sys.argv[2]) if len(sys.argv) > 2 else 10000
        logger.info(f"Running intraday sniper (Portfolio: ${portfolio_value:,.2f})...")
        opportunities = scan_intraday_opportunities(portfolio_value)
        
        logger.info("=" * 80)
        logger.info("INTRADAY SNIPER RESULTS")
        logger.info("=" * 80)
        logger.info(f"Opportunities found: {len(opportunities)}")
        
        if opportunities:
            for opp in opportunities:
                logger.info(f"{opp['ticker']} @ ${opp['entry_price']:.2f}")
                logger.info(f"  Metrics: {opp['metrics']}")
        else:
            logger.info("No opportunities found")

