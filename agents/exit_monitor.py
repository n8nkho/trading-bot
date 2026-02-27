import logging
import yfinance as yf
from datetime import datetime, timedelta
import sys
import os
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.local_llm import call_ollama
from agents.screener_agent import get_news_headlines

logging.basicConfig(
    filename='logs/exit_monitor.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Exit Configuration for Auto-Executed Trades
STOP_LOSS_PCT = -0.05  # -5% stop loss
PROFIT_TARGET_PCT = 0.10  # +10% profit target
MAX_HOLD_DAYS = 5  # Maximum hold period (time stop)

def check_option_exit(position):
    pass
def monitor_positions(positions):
    """
    Monitor open positions and generate exit decisions.
    
    Args:
        positions: List of position dicts with:
            - ticker: Stock symbol
            - entry_price: Entry price per share
            - qty or shares: Number of shares
            - entry_time or entry_date: Entry timestamp (ISO format string or datetime)
            - tiers_sold: Optional dict tracking which tiers have been sold
            
    Returns:
        List of exit decision dicts with action and reasoning
    """
    logging.info(f"Starting exit monitoring for {len(positions)} positions")
    
    decisions = []
    
    for pos in positions:
        ticker = pos['ticker']
        logging.info(f"Monitoring position: {ticker} ({pos.get('type', 'STOCK')})")
        
        try:
            if pos.get('type') == 'OPTION':
                decision = check_option_exit(pos)
            else:
                decision = evaluate_exit(pos)
            decisions.append(decision)
            
            logging.info(f"{ticker}: {decision['action']} - {decision['reason']}")
            
        except Exception as e:
            logging.error(f"Error monitoring {ticker}: {type(e).__name__}: {str(e)}")
            decisions.append({
                'ticker': ticker,
                'action': 'HOLD',
                'reason': f'Error during evaluation: {str(e)}',
                'current_price': None,
                'pnl_pct': None,
                'timestamp': datetime.now().isoformat()
            })
    
    action_summary = {}
    for d in decisions:
        action = d['action']
        action_summary[action] = action_summary.get(action, 0) + 1
    
    logging.info(f"Exit monitoring complete: {action_summary}")
    
    return decisions
    """
    Evaluate exit conditions for an option position.
    
    Args:
        position: Position dict with ticker, entry_premium, qty, expiration_date, type
        
    Returns:
        Decision dict with action, reason, sell_qty, current_price, pnl_pct
    """
def check_option_exit(position):
    ticker = position['ticker']
    entry_premium = position['entry_premium']
    qty = position['qty']
    expiration_date = datetime.fromisoformat(position['expiration_date'])
    
    # Calculate days to expiration (DTE)
    dte = (expiration_date - datetime.now()).days
    logging.info(f"{ticker}: Days to expiration (DTE): {dte}")
    
    # Fetch current option premium
    logging.info(f"{ticker}: Fetching current option premium...")
    option = yf.Ticker(ticker)
    current_data = option.history(period="1d", interval="1m")
    
    if len(current_data) == 0:
        logging.warning(f"{ticker}: No current premium data available")
        return create_hold_decision(ticker, "No current premium data available", None, None)
    
    current_premium = current_data['Close'].iloc[-1]
    profit_pct = (current_premium - entry_premium) / entry_premium * 100
    
    logging.info(f"{ticker}: Entry Premium: ${entry_premium:.2f}, Current Premium: ${current_premium:.2f}, Profit: {profit_pct:.2f}%")
    
    # Check 1: Stop Loss (-50%)
    if profit_pct <= -50:
        reason = f"Option stop loss triggered: {profit_pct:.2f}% <= -50%"
        logging.warning(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_premium, profit_pct, 
            stop_loss=True
        )
    
    # Check 2: Time Exit (< 14 DTE)
    if dte < 14:
        reason = f"Time exit: {dte} DTE < 14"
        logging.info(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_premium, profit_pct,
            time_limit=True
        )
    
    # Check 3: Theta Exit (< 7 DTE)
    if dte < 7:
        reason = f"Theta exit: {dte} DTE < 7"
        logging.info(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_premium, profit_pct,
            time_limit=True
        )
    
    # Check 4: Tiered Take Profits
    # Tier 3: +200% (sell remaining)
    if profit_pct >= 200:
        reason = f"Option take profit tier 3: {profit_pct:.2f}% >= 200%"
        logging.info(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_premium, profit_pct,
            tier='tier3'
        )
    
    # Tier 2: +100% (sell 30%)
    if profit_pct >= 100:
        sell_qty = int(qty * 0.30)
        if sell_qty > 0:
            reason = f"Option take profit tier 2: {profit_pct:.2f}% >= 100%"
            logging.info(f"{ticker}: {reason}")
            return create_exit_decision(
                ticker, 'SELL_30%', reason, sell_qty, current_premium, profit_pct,
                tier='tier2'
            )
    
    # Tier 1: +50% (sell 50%)
    if profit_pct >= 50:
        sell_qty = int(qty * 0.50)
        if sell_qty > 0:
            reason = f"Option take profit tier 1: {profit_pct:.2f}% >= 50%"
            logging.info(f"{ticker}: {reason}")
            return create_exit_decision(
                ticker, 'SELL_50%', reason, sell_qty, current_premium, profit_pct,
                tier='tier1'
            )
    
    # No exit conditions met - HOLD
    reason = f"No option exit conditions met (Profit: {profit_pct:.2f}%, DTE: {dte})"
    logging.info(f"{ticker}: {reason}")
    return create_hold_decision(ticker, reason, current_premium, profit_pct)

def monitor_positions(positions):
    """
    Monitor open positions and generate exit decisions.
    
    Args:
        positions: List of position dicts with:
            - ticker: Stock symbol
            - entry_price: Entry price per share
            - qty or shares: Number of shares
            - entry_time or entry_date: Entry timestamp (ISO format string or datetime)
            - tiers_sold: Optional dict tracking which tiers have been sold
            
    Returns:
        List of exit decision dicts with action and reasoning
    """
    logging.info(f"Starting exit monitoring for {len(positions)} positions")
    
    decisions = []
    
    for pos in positions:
        ticker = pos['ticker']
        logging.info(f"Monitoring position: {ticker} ({pos.get('type', 'STOCK')})")
        
        try:
            if pos.get('type') == 'OPTION':
                decision = check_option_exit(pos)
            else:
                decision = evaluate_exit(pos)
            decisions.append(decision)
            
            logging.info(f"{ticker}: {decision['action']} - {decision['reason']}")
            
        except Exception as e:
            logging.error(f"Error monitoring {ticker}: {type(e).__name__}: {str(e)}")
            decisions.append({
                'ticker': ticker,
                'action': 'HOLD',
                'reason': f'Error during evaluation: {str(e)}',
                'current_price': None,
                'pnl_pct': None,
                'timestamp': datetime.now().isoformat()
            })
    
    action_summary = {}
    for d in decisions:
        action = d['action']
        action_summary[action] = action_summary.get(action, 0) + 1
    
    logging.info(f"Exit monitoring complete: {action_summary}")
    
    return decisions

def evaluate_exit(position):
    """
    Evaluate exit conditions for a single position.
    
    Simplified exit rules for auto-executed trades:
    1. Stop loss: -5%
    2. Profit target: +10%
    3. Time stop: 5 days
    
    Args:
        position: Position dict with ticker, entry_price, qty/shares, entry_time/entry_date
        
    Returns:
        Decision dict with action, reason, sell_qty, current_price, pnl_pct
    """
    ticker = position['ticker']
    entry_price = position['entry_price']
    # Handle both 'qty' and 'shares' keys
    qty = position.get('qty') or position.get('shares', 0)
    # Handle both 'entry_time' and 'entry_date' keys
    entry_time = position.get('entry_time') or position.get('entry_date')
    
    # Parse entry time
    if isinstance(entry_time, str):
        entry_time = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
    
    # Get current price
    logging.info(f"{ticker}: Fetching current price...")
    stock = yf.Ticker(ticker)
    current_data = stock.history(period="1d", interval="1m")
    
    if len(current_data) == 0:
        logging.warning(f"{ticker}: No current price data available")
        return create_hold_decision(ticker, "No current price data available", None, None)
    
    current_price = current_data['Close'].iloc[-1]
    pnl_pct = (current_price - entry_price) / entry_price
    
    logging.info(f"{ticker}: Entry: ${entry_price:.2f}, Current: ${current_price:.2f}, P&L: {pnl_pct*100:.2f}%")
    
    # Check 1: Stop Loss (-5%)
    if pnl_pct <= STOP_LOSS_PCT:
        reason = f"Stop loss hit: {pnl_pct*100:.2f}% <= {STOP_LOSS_PCT*100:.2f}%"
        logging.warning(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_price, pnl_pct, 
            stop_loss=True
        )
    
    # Check 2: Profit Target (+10%)
    if pnl_pct >= PROFIT_TARGET_PCT:
        reason = f"Profit target hit: {pnl_pct*100:.2f}% >= {PROFIT_TARGET_PCT*100:.2f}%"
        logging.info(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_price, pnl_pct,
            profit_target=True
        )
    
    # Check 3: Time Stop (5 days)
    days_held = (datetime.now() - entry_time.replace(tzinfo=None)).days
    if days_held >= MAX_HOLD_DAYS:
        reason = f"Time stop: held {days_held} days >= {MAX_HOLD_DAYS} days"
        logging.info(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_price, pnl_pct,
            time_limit=True
        )
    
    # No exit conditions met - HOLD
    reason = f"No exit conditions met (P&L: {pnl_pct*100:.2f}%, Days: {days_held})"
    logging.info(f"{ticker}: {reason}")
    return create_hold_decision(ticker, reason, current_price, pnl_pct)

def check_negative_news(ticker):
    """
    Check for negative news using local LLM.
    
    Args:
        ticker: Stock symbol
        
    Returns:
        Dict with has_negative_news (bool) and summary (str)
    """
    try:
        logging.info(f"{ticker}: Checking for negative news...")
        
        # Get recent news headlines
        headlines = get_news_headlines(ticker, limit=5)
        
        if not headlines:
            logging.info(f"{ticker}: No news headlines found")
            return {'has_negative_news': False, 'summary': 'No recent news'}
        
        # Prepare prompt for LLM
        headlines_text = "\n".join([f"- {h}" for h in headlines])
        prompt = f"""Analyze these recent news headlines for {ticker} and determine if there is significant negative news that would warrant selling the position.

Headlines:
{headlines_text}

Respond with ONLY a JSON object in this exact format:
{{
  "has_negative_news": true or false,
  "summary": "brief explanation"
}}

Consider negative: earnings misses, regulatory issues, lawsuits, management changes, downgrades, guidance cuts.
Consider neutral/positive: normal market moves, analyst upgrades, product launches."""

        # Call local LLM
        response = call_ollama(prompt, model="llama3.1:8b", timeout=30)
        
        # Parse response
        import json
        # Try to extract JSON from response
        response = response.strip()
        if response.startswith('```'):
            # Remove code fence if present
            lines = response.split('\n')
            response = '\n'.join([l for l in lines if not l.startswith('```')])
        
        result = json.loads(response)
        
        has_negative = result.get('has_negative_news', False)
        summary = result.get('summary', 'Unable to analyze')
        
        logging.info(f"{ticker}: News analysis - Negative: {has_negative}, Summary: {summary}")
        
        return {
            'has_negative_news': has_negative,
            'summary': summary
        }
        
    except Exception as e:
        logging.error(f"{ticker}: Error checking news: {type(e).__name__}: {str(e)}")
        # On error, assume no negative news (fail safe)
        return {'has_negative_news': False, 'summary': f'Error analyzing news: {str(e)}'}

def create_exit_decision(ticker, action, reason, sell_qty, current_price, pnl_pct, 
                        stop_loss=False, time_limit=False, profit_target=False, negative_news=False, tier=None):
    """Create an exit decision dict"""
    return {
        'ticker': ticker,
        'action': action,
        'reason': reason,
        'sell_qty': sell_qty,
        'current_price': current_price,
        'pnl_pct': pnl_pct,
        'stop_loss': stop_loss,
        'time_limit': time_limit,
        'profit_target': profit_target,
        'negative_news': negative_news,
        'tier': tier,
        'timestamp': datetime.now().isoformat()
    }

def create_hold_decision(ticker, reason, current_price, pnl_pct):
    """Create a HOLD decision dict"""
    return {
        'ticker': ticker,
        'action': 'HOLD',
        'reason': reason,
        'sell_qty': 0,
        'current_price': current_price,
        'pnl_pct': pnl_pct,
        'stop_loss': False,
        'time_limit': False,
        'profit_target': False,
        'negative_news': False,
        'tier': None,
        'timestamp': datetime.now().isoformat()
    }

def execute_market_sell(ticker, qty, entry_price, exit_price, reason):
    """
    Execute a market sell order and log the exit.
    
    Args:
        ticker: Stock symbol
        qty: Number of shares to sell
        entry_price: Original entry price
        exit_price: Current exit price
        reason: Exit reason
        
    Returns:
        Dict with execution status and details
    """
    try:
        logging.info(f"{ticker}: Executing market sell order for {qty} shares at ${exit_price:.2f}")
        
        # Calculate P&L
        pnl_dollars = (exit_price - entry_price) * qty
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        
        # Log the exit
        exit_log = {
            'ticker': ticker,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'qty': qty,
            'pnl_dollars': pnl_dollars,
            'pnl_pct': pnl_pct,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }
        
        # Save to exit log file
        log_exit(exit_log)
        
        # Send SMS notification if configured
        send_exit_notification(exit_log)
        
        logging.info(f"{ticker}: Exit executed - P&L: ${pnl_dollars:.2f} ({pnl_pct:.2f}%)")
        
        return {
            'success': True,
            'ticker': ticker,
            'qty': qty,
            'exit_price': exit_price,
            'pnl_dollars': pnl_dollars,
            'pnl_pct': pnl_pct
        }
        
    except Exception as e:
        logging.error(f"{ticker}: Error executing market sell: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'ticker': ticker,
            'error': str(e)
        }

def log_exit(exit_log):
    """
    Log exit to data/exits.json
    
    Args:
        exit_log: Dict with exit details
    """
    try:
        # Ensure data directory exists
        Path('data').mkdir(exist_ok=True)
        
        exits_file = 'data/exits.json'
        
        # Load existing exits
        if os.path.exists(exits_file):
            with open(exits_file, 'r') as f:
                exits = json.load(f)
        else:
            exits = []
        
        # Append new exit
        exits.append(exit_log)
        
        # Save back to file
        with open(exits_file, 'w') as f:
            json.dump(exits, f, indent=2)
        
        logging.info(f"Exit logged to {exits_file}")
        
    except Exception as e:
        logging.error(f"Error logging exit: {type(e).__name__}: {str(e)}")

def send_exit_notification(exit_log):
    """
    Send SMS notification for exit (if configured).
    
    Args:
        exit_log: Dict with exit details
    """
    try:
        # Check if SMS is configured
        config_file = 'config/sms_config.json'
        if not os.path.exists(config_file):
            logging.info("SMS not configured, skipping notification")
            return
        
        with open(config_file, 'r') as f:
            sms_config = json.load(f)
        
        if not sms_config.get('enabled', False):
            logging.info("SMS notifications disabled, skipping")
            return
        
        # Format notification message
        ticker = exit_log['ticker']
        pnl_dollars = exit_log['pnl_dollars']
        pnl_pct = exit_log['pnl_pct']
        reason = exit_log['reason']
        
        message = f"EXIT: {ticker} - ${pnl_dollars:.2f} ({pnl_pct:.2f}%) - {reason}"
        
        # Send SMS (implementation depends on SMS provider)
        # For now, just log it
        logging.info(f"SMS notification: {message}")
        
        # TODO: Implement actual SMS sending using Twilio or similar
        # from twilio.rest import Client
        # client = Client(sms_config['account_sid'], sms_config['auth_token'])
        # client.messages.create(
        #     body=message,
        #     from_=sms_config['from_number'],
        #     to=sms_config['to_number']
        # )
        
    except Exception as e:
        logging.error(f"Error sending SMS notification: {type(e).__name__}: {str(e)}")

def process_exit_decisions(decisions):
    """
    Process exit decisions and execute market sell orders.
    
    Args:
        decisions: List of exit decision dicts
        
    Returns:
        List of execution results
    """
    results = []
    
    for decision in decisions:
        if decision['action'] == 'HOLD':
            continue
        
        ticker = decision['ticker']
        sell_qty = decision['sell_qty']
        current_price = decision['current_price']
        reason = decision['reason']
        
        # Get entry price from position (need to load positions)
        positions = load_positions()
        position = next((p for p in positions if p['ticker'] == ticker), None)
        
        if not position:
            logging.error(f"{ticker}: Position not found, cannot execute exit")
            continue
        
        entry_price = position['entry_price']
        
        # Execute market sell
        result = execute_market_sell(ticker, sell_qty, entry_price, current_price, reason)
        results.append(result)
    
    return results

def load_positions():
    """Load positions from data/positions.json"""
    try:
        positions_file = 'data/positions.json'
        if os.path.exists(positions_file):
            with open(positions_file, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        logging.error(f"Error loading positions: {type(e).__name__}: {str(e)}")
        return []

if __name__ == "__main__":
    # Load actual positions from data/positions.json
    positions = load_positions()
    
    if not positions:
        print("No positions found in data/positions.json")
        print("\nUsing sample positions for testing...")
        positions = [
            {
                'ticker': 'AAPL',
                'entry_price': 150.00,
                'qty': 10,
                'entry_time': (datetime.now() - timedelta(hours=2)).isoformat()
            },
            {
                'ticker': 'MSFT',
                'entry_price': 300.00,
                'qty': 5,
                'entry_time': (datetime.now() - timedelta(days=2)).isoformat()
            },
            {
                'ticker': 'GOOGL',
                'entry_price': 140.00,
                'qty': 8,
                'entry_time': (datetime.now() - timedelta(days=6)).isoformat()
            }
        ]
    
    print("Exit Monitor - Auto-Executed Trades")
    print("=" * 60)
    print(f"Stop Loss: {STOP_LOSS_PCT*100:.1f}%")
    print(f"Profit Target: {PROFIT_TARGET_PCT*100:.1f}%")
    print(f"Time Stop: {MAX_HOLD_DAYS} days")
    print("=" * 60)
    
    # Monitor positions
    decisions = monitor_positions(positions)
    
    print("\nExit Decisions:")
    print("-" * 60)
    for decision in decisions:
        print(f"\n{decision['ticker']}: {decision['action']}")
        print(f"  Reason: {decision['reason']}")
        if decision['current_price']:
            print(f"  Current Price: ${decision['current_price']:.2f}")
        if decision['pnl_pct'] is not None:
            print(f"  P&L: {decision['pnl_pct']*100:.2f}%")
        if decision['sell_qty'] > 0:
            print(f"  Sell Quantity: {decision['sell_qty']} shares")
    
    # Save decisions to file
    filename = f"data/exit_decisions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    Path('data').mkdir(exist_ok=True)
    with open(filename, 'w') as f:
        json.dump(decisions, f, indent=2)
    print(f"\nDecisions saved to {filename}")
    
    # Process exits (execute market sells)
    print("\nProcessing Exits:")
    print("-" * 60)
    results = process_exit_decisions(decisions)
    
    for result in results:
        if result['success']:
            print(f"\n✓ {result['ticker']}: Sold {result['qty']} shares at ${result['exit_price']:.2f}")
            print(f"  P&L: ${result['pnl_dollars']:.2f} ({result['pnl_pct']:.2f}%)")
        else:
            print(f"\n✗ {result['ticker']}: Failed - {result['error']}")
    
    print("\n" + "=" * 60)
    print("Exit monitoring complete")
