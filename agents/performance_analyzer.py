"""
Performance Analyzer - Self-Improving Trading System
Tracks decisions, analyzes outcomes, and automatically tunes parameters based on performance
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import statistics

from utils.local_llm import call_ollama

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

DECISIONS_LOG = DATA_DIR / "decisions_log.jsonl"
PARAMETER_HISTORY = DATA_DIR / "parameter_history.json"
CURRENT_PARAMS = DATA_DIR / "current_params.json"

# Default parameters
DEFAULT_PARAMS = {
    'rsi_threshold': 40,
    'drop_min': -15,
    'drop_max': -5,
    'volume_ratio_min': 1.5,
    'stop_loss_pct': -2.0,
    'take_profit_pct': 5.0,
    'sector_allocations': {},
    'last_updated': None
}


def track_decision(signal_id, decision_data):
    """
    Record a trading decision for future analysis.
    
    Args:
        signal_id: Unique identifier for this signal (e.g., "AAPL_20260221_093000")
        decision_data: Dict containing:
            - ticker: Stock ticker
            - action: BUY/SKIP
            - entry_price: Entry price (if BUY)
            - shares: Number of shares (if BUY)
            - position_size: Total position value (if BUY)
            - confidence: Confidence score (0-1)
            - reasoning: Why this decision was made
            - metrics: Dict of technical metrics (rsi, drop_pct, volume_ratio, etc.)
            - grok_sentiment: Sentiment from Grok (if available)
            - timestamp: ISO timestamp
    
    Returns:
        bool: True if successfully logged
    """
    try:
        # Add signal_id and outcome placeholder
        record = {
            'signal_id': signal_id,
            'decision': decision_data,
            'outcome': None,  # Will be filled by track_outcome()
            'logged_at': datetime.now().isoformat()
        }
        
        # Append to JSONL file
        with open(DECISIONS_LOG, 'a') as f:
            f.write(json.dumps(record) + '\n')
        
        logger.info(f"Tracked decision: {signal_id} - {decision_data['ticker']} {decision_data['action']}")
        return True
        
    except Exception as e:
        logger.error(f"Error tracking decision {signal_id}: {type(e).__name__}: {str(e)}")
        return False


def track_outcome(signal_id, outcome_data):
    """
    Record the outcome of a trading decision.
    
    Args:
        signal_id: Signal ID to update
        outcome_data: Dict containing:
            - exit_price: Exit price
            - pnl_pct: P&L percentage
            - pnl_dollars: P&L in dollars
            - hold_days: Number of days held
            - exit_reason: Why position was closed
            - exit_timestamp: ISO timestamp of exit
    
    Returns:
        bool: True if successfully updated
    """
    try:
        # Read all records
        if not DECISIONS_LOG.exists():
            logger.warning(f"Decisions log not found: {DECISIONS_LOG}")
            return False
        
        records = []
        updated = False
        
        with open(DECISIONS_LOG, 'r') as f:
            for line in f:
                record = json.loads(line.strip())
                
                # Update matching record
                if record['signal_id'] == signal_id:
                    record['outcome'] = outcome_data
                    record['outcome_logged_at'] = datetime.now().isoformat()
                    updated = True
                    logger.info(f"Updated outcome for {signal_id}: P&L {outcome_data['pnl_pct']:.2f}%")
                
                records.append(record)
        
        if not updated:
            logger.warning(f"Signal ID not found: {signal_id}")
            return False
        
        # Write back all records
        with open(DECISIONS_LOG, 'w') as f:
            for record in records:
                f.write(json.dumps(record) + '\n')
        
        return True
        
    except Exception as e:
        logger.error(f"Error tracking outcome {signal_id}: {type(e).__name__}: {str(e)}")
        return False


def analyze_performance(lookback_days=30):
    """
    Analyze trading performance over the last N days.
    
    Args:
        lookback_days: Number of days to analyze
    
    Returns:
        dict: Performance metrics and insights
    """
    logger.info(f"Analyzing performance for last {lookback_days} days...")
    
    try:
        # Load decisions with outcomes
        cutoff_date = datetime.now() - timedelta(days=lookback_days)
        trades = []
        
        if not DECISIONS_LOG.exists():
            logger.warning("No decisions log found")
            return {
                'error': 'No decisions log found',
                'trades_analyzed': 0
            }
        
        with open(DECISIONS_LOG, 'r') as f:
            for line in f:
                record = json.loads(line.strip())
                
                # Only include completed trades (BUY with outcome)
                if (record['decision']['action'] == 'BUY' and 
                    record['outcome'] is not None):
                    
                    logged_at = datetime.fromisoformat(record['logged_at'])
                    if logged_at >= cutoff_date:
                        trades.append(record)
        
        if len(trades) == 0:
            logger.info("No completed trades found in lookback period")
            return {
                'trades_analyzed': 0,
                'message': 'No completed trades in lookback period'
            }
        
        logger.info(f"Analyzing {len(trades)} completed trades...")
        
        # Calculate basic metrics
        wins = [t for t in trades if t['outcome']['pnl_pct'] > 0]
        losses = [t for t in trades if t['outcome']['pnl_pct'] <= 0]
        
        win_rate = len(wins) / len(trades) if trades else 0
        avg_win = statistics.mean([t['outcome']['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = statistics.mean([t['outcome']['pnl_pct'] for t in losses]) if losses else 0
        avg_hold_days = statistics.mean([t['outcome']['hold_days'] for t in trades])
        
        # Analyze by RSI ranges
        rsi_performance = analyze_by_metric(trades, 'rsi', [(0, 30), (30, 35), (35, 40), (40, 50)])
        
        # Analyze by drop percentage ranges
        drop_performance = analyze_by_metric(trades, 'drop_pct', [(-20, -15), (-15, -10), (-10, -5), (-5, 0)])
        
        # Analyze by sector
        sector_performance = analyze_by_sector(trades)
        
        # Analyze by confidence ranges
        confidence_performance = analyze_by_metric(trades, 'confidence', [(0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)])
        
        metrics = {
            'trades_analyzed': len(trades),
            'lookback_days': lookback_days,
            'win_rate': win_rate,
            'wins': len(wins),
            'losses': len(losses),
            'avg_win_pct': avg_win,
            'avg_loss_pct': avg_loss,
            'avg_hold_days': avg_hold_days,
            'best_rsi_range': rsi_performance['best_range'],
            'best_drop_range': drop_performance['best_range'],
            'best_sector': sector_performance['best_sector'],
            'best_confidence_range': confidence_performance['best_range'],
            'rsi_analysis': rsi_performance['details'],
            'drop_analysis': drop_performance['details'],
            'sector_analysis': sector_performance['details'],
            'confidence_analysis': confidence_performance['details']
        }
        
        # Use local Llama to find patterns
        logger.info("Using Llama to analyze patterns...")
        llm_insights = get_llm_insights(trades, metrics)
        metrics['llm_insights'] = llm_insights
        
        logger.info(f"Analysis complete: {win_rate*100:.1f}% win rate, {len(trades)} trades")
        
        return metrics
        
    except Exception as e:
        logger.error(f"Error analyzing performance: {type(e).__name__}: {str(e)}")
        return {
            'error': str(e),
            'trades_analyzed': 0
        }


def analyze_by_metric(trades, metric_name, ranges):
    """
    Analyze performance by metric ranges.
    
    Args:
        trades: List of trade records
        metric_name: Name of metric in decision.metrics
        ranges: List of (min, max) tuples
    
    Returns:
        dict: Best range and details
    """
    range_stats = {}
    
    for min_val, max_val in ranges:
        range_trades = [
            t for t in trades 
            if min_val <= t['decision']['metrics'].get(metric_name, 0) < max_val
        ]
        
        if range_trades:
            wins = [t for t in range_trades if t['outcome']['pnl_pct'] > 0]
            win_rate = len(wins) / len(range_trades)
            avg_pnl = statistics.mean([t['outcome']['pnl_pct'] for t in range_trades])
            
            range_stats[f"{min_val}-{max_val}"] = {
                'trades': len(range_trades),
                'win_rate': win_rate,
                'avg_pnl_pct': avg_pnl
            }
    
    # Find best range by win rate
    best_range = None
    best_win_rate = 0
    
    for range_name, stats in range_stats.items():
        if stats['trades'] >= 3 and stats['win_rate'] > best_win_rate:
            best_win_rate = stats['win_rate']
            best_range = range_name
    
    return {
        'best_range': best_range,
        'details': range_stats
    }


def analyze_by_sector(trades):
    """
    Analyze performance by sector.
    
    Args:
        trades: List of trade records
    
    Returns:
        dict: Best sector and details
    """
    sector_stats = defaultdict(lambda: {'trades': [], 'wins': 0})
    
    for trade in trades:
        # Get sector from decision data (may need to extract from candidate info)
        ticker = trade['decision']['ticker']
        sector = trade['decision'].get('sector', 'Unknown')
        
        sector_stats[sector]['trades'].append(trade)
        if trade['outcome']['pnl_pct'] > 0:
            sector_stats[sector]['wins'] += 1
    
    # Calculate stats
    sector_details = {}
    for sector, data in sector_stats.items():
        trades_count = len(data['trades'])
        win_rate = data['wins'] / trades_count if trades_count > 0 else 0
        avg_pnl = statistics.mean([t['outcome']['pnl_pct'] for t in data['trades']])
        
        sector_details[sector] = {
            'trades': trades_count,
            'win_rate': win_rate,
            'avg_pnl_pct': avg_pnl
        }
    
    # Find best sector
    best_sector = None
    best_win_rate = 0
    
    for sector, stats in sector_details.items():
        if stats['trades'] >= 3 and stats['win_rate'] > best_win_rate:
            best_win_rate = stats['win_rate']
            best_sector = sector
    
    return {
        'best_sector': best_sector,
        'details': sector_details
    }


def get_llm_insights(trades, metrics):
    """
    Use local Llama to analyze patterns and generate insights.
    
    Args:
        trades: List of trade records
        metrics: Performance metrics dict
    
    Returns:
        dict: LLM-generated insights
    """
    try:
        # Prepare summary for LLM
        trade_summaries = []
        for trade in trades[:20]:  # Limit to 20 most recent
            summary = {
                'ticker': trade['decision']['ticker'],
                'rsi': trade['decision']['metrics'].get('rsi'),
                'drop_pct': trade['decision']['metrics'].get('drop_pct'),
                'confidence': trade['decision']['metrics'].get('confidence'),
                'pnl_pct': trade['outcome']['pnl_pct'],
                'hold_days': trade['outcome']['hold_days'],
                'won': trade['outcome']['pnl_pct'] > 0
            }
            trade_summaries.append(summary)
        
        prompt = f"""Analyze these {len(trade_summaries)} recent trades and identify winning patterns.

Performance Summary:
- Win Rate: {metrics['win_rate']*100:.1f}%
- Average Win: {metrics['avg_win_pct']:.2f}%
- Average Loss: {metrics['avg_loss_pct']:.2f}%
- Best RSI Range: {metrics['best_rsi_range']}
- Best Drop Range: {metrics['best_drop_range']}

Recent Trades:
{json.dumps(trade_summaries, indent=2)}

Analyze the data and return a JSON object with:
1. "key_patterns": List of 2-3 patterns that correlate with winning trades
2. "avoid_patterns": List of 2-3 patterns that correlate with losing trades
3. "parameter_suggestions": Specific RSI/drop/confidence thresholds to improve win rate
4. "confidence_score": Your confidence in these insights (0-1)

Return ONLY valid JSON, no other text."""

        logger.info("Calling Llama for pattern analysis...")
        response = call_ollama(prompt, model="llama3.1:8b", timeout=90)
        
        # Parse JSON response
        try:
            insights = json.loads(response)
            logger.info("LLM insights generated successfully")
            return insights
        except json.JSONDecodeError:
            logger.warning("LLM response was not valid JSON, returning raw response")
            return {
                'raw_response': response,
                'parse_error': 'Could not parse JSON'
            }
        
    except Exception as e:
        logger.error(f"Error getting LLM insights: {type(e).__name__}: {str(e)}")
        return {
            'error': str(e)
        }


def auto_tune_parameters():
    """
    Automatically tune trading parameters based on recent performance.
    
    Rules:
    - If win_rate < 45% for 20+ trades → widen RSI to < 45
    - If win_rate > 60% for 20+ trades → tighten RSI to < 35
    - If avg_loss > 2.5% → tighten stop loss to -1.5%
    - If best_sector identified → increase allocation 20%
    
    Returns:
        dict: Tuning results and changes made
    """
    logger.info("=" * 80)
    logger.info("AUTO-TUNING PARAMETERS")
    logger.info("=" * 80)
    
    try:
        # Load current parameters
        current_params = load_current_params()
        original_params = current_params.copy()
        
        # Analyze recent performance
        metrics = analyze_performance(lookback_days=30)
        
        if metrics.get('trades_analyzed', 0) < 20:
            logger.info(f"Insufficient trades for tuning ({metrics.get('trades_analyzed', 0)} < 20)")
            return {
                'tuned': False,
                'reason': 'Insufficient trades (need 20+)',
                'trades_analyzed': metrics.get('trades_analyzed', 0)
            }
        
        changes_made = []
        
        # Rule 1: Adjust RSI based on win rate
        win_rate = metrics['win_rate']
        trades_count = metrics['trades_analyzed']
        
        if win_rate < 0.45:
            logger.info(f"Win rate {win_rate*100:.1f}% < 45% - widening RSI threshold")
            current_params['rsi_threshold'] = 45
            changes_made.append({
                'parameter': 'rsi_threshold',
                'old_value': original_params['rsi_threshold'],
                'new_value': 45,
                'reason': f'Win rate {win_rate*100:.1f}% below 45%'
            })
        
        elif win_rate > 0.60:
            logger.info(f"Win rate {win_rate*100:.1f}% > 60% - tightening RSI threshold")
            current_params['rsi_threshold'] = 35
            changes_made.append({
                'parameter': 'rsi_threshold',
                'old_value': original_params['rsi_threshold'],
                'new_value': 35,
                'reason': f'Win rate {win_rate*100:.1f}% above 60%'
            })
        
        # Rule 2: Adjust stop loss based on average loss
        avg_loss = abs(metrics['avg_loss_pct'])
        
        if avg_loss > 2.5:
            logger.info(f"Average loss {avg_loss:.2f}% > 2.5% - tightening stop loss")
            current_params['stop_loss_pct'] = -1.5
            changes_made.append({
                'parameter': 'stop_loss_pct',
                'old_value': original_params['stop_loss_pct'],
                'new_value': -1.5,
                'reason': f'Average loss {avg_loss:.2f}% exceeds 2.5%'
            })
        
        # Rule 3: Adjust sector allocations based on best sector
        best_sector = metrics.get('best_sector')
        
        if best_sector and best_sector != 'Unknown':
            sector_stats = metrics['sector_analysis'].get(best_sector, {})
            sector_win_rate = sector_stats.get('win_rate', 0)
            
            if sector_win_rate > 0.60:
                logger.info(f"Best sector {best_sector} has {sector_win_rate*100:.1f}% win rate - increasing allocation")
                
                if 'sector_allocations' not in current_params:
                    current_params['sector_allocations'] = {}
                
                old_allocation = current_params['sector_allocations'].get(best_sector, 1.0)
                new_allocation = min(old_allocation * 1.2, 1.5)  # Cap at 1.5x
                
                current_params['sector_allocations'][best_sector] = new_allocation
                changes_made.append({
                    'parameter': f'sector_allocation_{best_sector}',
                    'old_value': old_allocation,
                    'new_value': new_allocation,
                    'reason': f'Sector win rate {sector_win_rate*100:.1f}% above 60%'
                })
        
        # Rule 4: Use LLM insights for additional tuning
        llm_insights = metrics.get('llm_insights', {})
        if 'parameter_suggestions' in llm_insights:
            suggestions = llm_insights['parameter_suggestions']
            logger.info(f"LLM parameter suggestions: {suggestions}")
            
            # Apply LLM suggestions if confidence is high
            if llm_insights.get('confidence_score', 0) > 0.7:
                # Example: Apply RSI suggestion if provided
                if 'rsi_threshold' in suggestions:
                    suggested_rsi = suggestions['rsi_threshold']
                    if 30 <= suggested_rsi <= 50:  # Sanity check
                        current_params['rsi_threshold'] = suggested_rsi
                        changes_made.append({
                            'parameter': 'rsi_threshold',
                            'old_value': original_params['rsi_threshold'],
                            'new_value': suggested_rsi,
                            'reason': f'LLM suggestion (confidence: {llm_insights["confidence_score"]:.2f})'
                        })
        
        # Save updated parameters
        if changes_made:
            current_params['last_updated'] = datetime.now().isoformat()
            save_current_params(current_params)
            save_parameter_history(original_params, current_params, changes_made, metrics)
            
            logger.info(f"Parameters tuned: {len(changes_made)} changes made")
            for change in changes_made:
                logger.info(f"  {change['parameter']}: {change['old_value']} → {change['new_value']}")
        else:
            logger.info("No parameter changes needed")
        
        result = {
            'tuned': len(changes_made) > 0,
            'trades_analyzed': trades_count,
            'win_rate': win_rate,
            'changes_made': changes_made,
            'new_parameters': current_params,
            'metrics': metrics
        }
        
        logger.info("=" * 80)
        logger.info(f"AUTO-TUNING COMPLETE: {len(changes_made)} changes")
        logger.info("=" * 80)
        
        return result
        
    except Exception as e:
        logger.error(f"Error auto-tuning parameters: {type(e).__name__}: {str(e)}")
        return {
            'tuned': False,
            'error': str(e)
        }


def weekly_review():
    """
    Generate weekly performance review and insights.
    Runs Sunday at midnight.
    
    Returns:
        dict: Weekly review report
    """
    logger.info("=" * 80)
    logger.info("WEEKLY PERFORMANCE REVIEW")
    logger.info("=" * 80)
    
    try:
        # Analyze last week's performance
        metrics = analyze_performance(lookback_days=7)
        
        if metrics.get('trades_analyzed', 0) == 0:
            logger.info("No trades to review this week")
            return {
                'week_ending': datetime.now().isoformat(),
                'trades': 0,
                'message': 'No trades this week'
            }
        
        # Generate insights report
        report = {
            'week_ending': datetime.now().isoformat(),
            'trades_analyzed': metrics['trades_analyzed'],
            'win_rate': metrics['win_rate'],
            'wins': metrics['wins'],
            'losses': metrics['losses'],
            'avg_win_pct': metrics['avg_win_pct'],
            'avg_loss_pct': metrics['avg_loss_pct'],
            'avg_hold_days': metrics['avg_hold_days'],
            'best_rsi_range': metrics['best_rsi_range'],
            'best_drop_range': metrics['best_drop_range'],
            'best_sector': metrics['best_sector'],
            'llm_insights': metrics.get('llm_insights', {})
        }
        
        # Check if auto-tuning is recommended
        if metrics['trades_analyzed'] >= 20:
            logger.info("Sufficient trades for auto-tuning - running parameter optimization...")
            tuning_result = auto_tune_parameters()
            report['auto_tuning'] = tuning_result
        else:
            report['auto_tuning'] = {
                'recommended': False,
                'reason': f'Need 20+ trades (have {metrics["trades_analyzed"]})'
            }
        
        # Save weekly report
        week_str = datetime.now().strftime('%Y_W%U')
        report_file = DATA_DIR / f"weekly_review_{week_str}.json"
        
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Weekly review saved to {report_file}")
        logger.info(f"Week summary: {metrics['trades_analyzed']} trades, {metrics['win_rate']*100:.1f}% win rate")
        logger.info("=" * 80)
        
        return report
        
    except Exception as e:
        logger.error(f"Error generating weekly review: {type(e).__name__}: {str(e)}")
        return {
            'week_ending': datetime.now().isoformat(),
            'error': str(e)
        }


def load_current_params():
    """Load current trading parameters."""
    try:
        if CURRENT_PARAMS.exists():
            with open(CURRENT_PARAMS, 'r') as f:
                return json.load(f)
        else:
            logger.info("No current params file, using defaults")
            return DEFAULT_PARAMS.copy()
    except Exception as e:
        logger.error(f"Error loading current params: {e}")
        return DEFAULT_PARAMS.copy()


def save_current_params(params):
    """Save current trading parameters."""
    try:
        with open(CURRENT_PARAMS, 'w') as f:
            json.dump(params, f, indent=2)
        logger.info(f"Parameters saved to {CURRENT_PARAMS}")
    except Exception as e:
        logger.error(f"Error saving current params: {e}")


def save_parameter_history(old_params, new_params, changes, metrics):
    """Save parameter change history."""
    try:
        # Load existing history
        if PARAMETER_HISTORY.exists():
            with open(PARAMETER_HISTORY, 'r') as f:
                history = json.load(f)
        else:
            history = {'changes': []}
        
        # Add new change record
        history['changes'].append({
            'timestamp': datetime.now().isoformat(),
            'old_params': old_params,
            'new_params': new_params,
            'changes': changes,
            'performance_metrics': {
                'trades_analyzed': metrics['trades_analyzed'],
                'win_rate': metrics['win_rate'],
                'avg_win_pct': metrics['avg_win_pct'],
                'avg_loss_pct': metrics['avg_loss_pct']
            }
        })
        
        # Save history
        with open(PARAMETER_HISTORY, 'w') as f:
            json.dump(history, f, indent=2)
        
        logger.info(f"Parameter history updated: {PARAMETER_HISTORY}")
        
    except Exception as e:
        logger.error(f"Error saving parameter history: {e}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python agents/performance_analyzer.py analyze [days]  - Analyze performance")
        print("  python agents/performance_analyzer.py tune            - Auto-tune parameters")
        print("  python agents/performance_analyzer.py review           - Weekly review")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "analyze":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print(f"\nAnalyzing performance for last {days} days...\n")
        
        metrics = analyze_performance(days)
        
        print("=" * 80)
        print("PERFORMANCE ANALYSIS")
        print("=" * 80)
        print(f"Trades analyzed: {metrics.get('trades_analyzed', 0)}")
        print(f"Win rate: {metrics.get('win_rate', 0)*100:.1f}%")
        print(f"Average win: {metrics.get('avg_win_pct', 0):.2f}%")
        print(f"Average loss: {metrics.get('avg_loss_pct', 0):.2f}%")
        print(f"Average hold days: {metrics.get('avg_hold_days', 0):.1f}")
        print(f"\nBest RSI range: {metrics.get('best_rsi_range', 'N/A')}")
        print(f"Best drop range: {metrics.get('best_drop_range', 'N/A')}")
        print(f"Best sector: {metrics.get('best_sector', 'N/A')}")
        
        if 'llm_insights' in metrics and 'key_patterns' in metrics['llm_insights']:
            print(f"\nKey Patterns (LLM):")
            for pattern in metrics['llm_insights']['key_patterns']:
                print(f"  - {pattern}")
    
    elif command == "tune":
        print("\nAuto-tuning parameters...\n")
        result = auto_tune_parameters()
        
        print("=" * 80)
        print("AUTO-TUNING RESULTS")
        print("=" * 80)
        print(f"Tuned: {result['tuned']}")
        print(f"Trades analyzed: {result.get('trades_analyzed', 0)}")
        
        if result['tuned']:
            print(f"\nChanges made:")
            for change in result['changes_made']:
                print(f"  {change['parameter']}: {change['old_value']} → {change['new_value']}")
                print(f"    Reason: {change['reason']}")
        else:
            print(f"\nReason: {result.get('reason', 'No changes needed')}")
    
    elif command == "review":
        print("\nGenerating weekly review...\n")
        report = weekly_review()
        
        print("=" * 80)
        print("WEEKLY REVIEW")
        print("=" * 80)
        print(f"Week ending: {report['week_ending']}")
        print(f"Trades: {report.get('trades_analyzed', 0)}")
        
        if report.get('trades_analyzed', 0) > 0:
            print(f"Win rate: {report['win_rate']*100:.1f}%")
            print(f"Average win: {report['avg_win_pct']:.2f}%")
            print(f"Average loss: {report['avg_loss_pct']:.2f}%")
            
            if 'auto_tuning' in report and report['auto_tuning'].get('tuned'):
                print(f"\nAuto-tuning applied: {len(report['auto_tuning']['changes_made'])} changes")
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
