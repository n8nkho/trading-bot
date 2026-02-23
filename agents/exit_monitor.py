import logging
import yfinance as yf
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.local_llm import call_ollama
from agents.screener_agent import get_news_headlines

logging.basicConfig(
    filename='logs/exit_monitor.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Exit Configuration
STOP_LOSS_PCT = -0.02  # -2% stop loss
TAKE_PROFIT_T1_PCT = 0.015  # +1.5% take profit tier 1
TAKE_PROFIT_T2_PCT = 0.03  # +3% take profit tier 2
TAKE_PROFIT_T3_PCT = 0.05  # +5% take profit tier 3
MAX_HOLD_DAYS = 3  # Maximum hold period

# Tier sell percentages
TIER_1_SELL_PCT = 0.50  # Sell 50% at tier 1
TIER_2_SELL_PCT = 0.30  # Sell 30% at tier 2
TIER_3_SELL_PCT = 0.20  # Sell remaining 20% at tier 3

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
    
    Args:
        position: Position dict with ticker, entry_price, qty/shares, entry_time/entry_date, tiers_sold
        
    Returns:
        Decision dict with action, reason, sell_qty, current_price, pnl_pct
    """
    ticker = position['ticker']
    entry_price = position['entry_price']
    # Handle both 'qty' and 'shares' keys
    qty = position.get('qty') or position.get('shares', 0)
    # Handle both 'entry_time' and 'entry_date' keys
    entry_time = position.get('entry_time') or position.get('entry_date')
    tiers_sold = position.get('tiers_sold', {'tier1': False, 'tier2': False, 'tier3': False})
    
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
    
    # Check 1: Stop Loss (-2%)
    if pnl_pct <= STOP_LOSS_PCT:
        reason = f"Stop loss triggered: {pnl_pct*100:.2f}% <= {STOP_LOSS_PCT*100:.2f}%"
        logging.warning(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_price, pnl_pct, 
            stop_loss=True
        )
    
    # Check 2: Time Limit (3 days)
    days_held = (datetime.now() - entry_time.replace(tzinfo=None)).days
    if days_held >= MAX_HOLD_DAYS:
        reason = f"Time limit reached: {days_held} days >= {MAX_HOLD_DAYS} days"
        logging.info(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_price, pnl_pct,
            time_limit=True
        )
    
    # Check 3: Negative News
    news_check = check_negative_news(ticker)
    if news_check['has_negative_news']:
        reason = f"Negative news detected: {news_check['summary']}"
        logging.warning(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_price, pnl_pct,
            negative_news=True
        )
    
    # Check 4: Tiered Take Profits
    # Tier 3: +5% (sell remaining 20%)
    if pnl_pct >= TAKE_PROFIT_T3_PCT and not tiers_sold['tier3']:
        sell_qty = int(qty * TIER_3_SELL_PCT)
        if sell_qty > 0:
            reason = f"Take profit tier 3: {pnl_pct*100:.2f}% >= {TAKE_PROFIT_T3_PCT*100:.2f}%"
            logging.info(f"{ticker}: {reason}")
            return create_exit_decision(
                ticker, 'SELL_20%', reason, sell_qty, current_price, pnl_pct,
                tier='tier3'
            )
    
    # Tier 2: +3% (sell 30%)
    if pnl_pct >= TAKE_PROFIT_T2_PCT and not tiers_sold['tier2']:
        sell_qty = int(qty * TIER_2_SELL_PCT)
        if sell_qty > 0:
            reason = f"Take profit tier 2: {pnl_pct*100:.2f}% >= {TAKE_PROFIT_T2_PCT*100:.2f}%"
            logging.info(f"{ticker}: {reason}")
            return create_exit_decision(
                ticker, 'SELL_30%', reason, sell_qty, current_price, pnl_pct,
                tier='tier2'
            )
    
    # Tier 1: +1.5% (sell 50%)
    if pnl_pct >= TAKE_PROFIT_T1_PCT and not tiers_sold['tier1']:
        sell_qty = int(qty * TIER_1_SELL_PCT)
        if sell_qty > 0:
            reason = f"Take profit tier 1: {pnl_pct*100:.2f}% >= {TAKE_PROFIT_T1_PCT*100:.2f}%"
            logging.info(f"{ticker}: {reason}")
            return create_exit_decision(
                ticker, 'SELL_50%', reason, sell_qty, current_price, pnl_pct,
                tier='tier1'
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
                        stop_loss=False, time_limit=False, negative_news=False, tier=None):
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
        'negative_news': False,
        'tier': None,
        'timestamp': datetime.now().isoformat()
    }

if __name__ == "__main__":
    # Test with sample positions
    import json
    
    sample_positions = [
        {
            'ticker': 'AAPL',
            'entry_price': 150.00,
            'qty': 10,
            'entry_time': (datetime.now() - timedelta(hours=2)).isoformat(),
            'tiers_sold': {'tier1': False, 'tier2': False, 'tier3': False}
        },
        {
            'ticker': 'MSFT',
            'entry_price': 300.00,
            'qty': 5,
            'entry_time': (datetime.now() - timedelta(days=2)).isoformat(),
            'tiers_sold': {'tier1': True, 'tier2': False, 'tier3': False}
        },
        {
            'ticker': 'GOOGL',
            'entry_price': 140.00,
            'qty': 8,
            'entry_time': (datetime.now() - timedelta(days=4)).isoformat(),
            'tiers_sold': {'tier1': False, 'tier2': False, 'tier3': False}
        }
    ]
    
    print("Exit Monitor Test Run")
    print("=" * 60)
    
    decisions = monitor_positions(sample_positions)
    
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
        if decision['tier']:
            print(f"  Tier: {decision['tier']}")
    
    # Save decisions to file
    filename = f"data/exit_decisions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, 'w') as f:
        json.dump(decisions, f, indent=2)
    print(f"\nDecisions saved to {filename}")
