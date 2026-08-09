"""
Meta-Architect Agent: Self-Improving Agent Creator
Analyzes trading performance, identifies weaknesses, and autonomously creates new specialized agents.
"""

import json
import logging
import os
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import subprocess
from typing import Any

from utils.local_llm import call_llm

# Setup logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "meta_architect.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Configuration
DATA_DIR = Path("data")
AGENTS_DIR = Path("agents")
DECISIONS_LOG = DATA_DIR / "decisions_log.jsonl"
GENERATED_AGENTS_DIR = AGENTS_DIR / "generated"
GENERATED_AGENTS_DIR.mkdir(exist_ok=True)

MIN_TRADES_REQUIRED = 100  # Minimum trades before creating agents
MAX_GENERATED_AGENTS = 10  # Maximum number of generated agents
IMPROVEMENT_THRESHOLD = 0.05  # 5% improvement required to keep agent
LOOKBACK_DAYS = 30  # Days of data to analyze


def _adaptive_meta_enabled() -> bool:
    return str(os.environ.get("FORTRESS_META_ARCHITECT_ADAPTIVE_ENABLED", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _early_trade_floor() -> int:
    try:
        return max(10, int(os.environ.get("FORTRESS_META_ARCHITECT_EARLY_TRADE_FLOOR", "30")))
    except ValueError:
        return 30


def _gap_cycles_required() -> int:
    try:
        return max(2, int(os.environ.get("FORTRESS_META_ARCHITECT_GAP_CYCLES", "3")))
    except ValueError:
        return 3


def _fortress_capability_gap_streak() -> int:
    """Count consecutive capability reviews with objective gaps (fortress-ai sibling)."""
    import json

    log_path = Path("/home/ubuntu/fortress-ai/data/si_capability/review_log.jsonl")
    if not log_path.is_file():
        tb = Path(__file__).resolve().parent.parent
        alt = tb.parent / "fortress-ai" / "data" / "si_capability" / "review_log.jsonl"
        log_path = alt if alt.is_file() else log_path
    if not log_path.is_file():
        return 0
    streak = 0
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines[-20:]):
            if not line.strip():
                continue
            row = json.loads(line)
            gaps = int(row.get("gaps") or 0)
            if gaps > 0:
                streak += 1
            else:
                break
    except Exception:
        return 0
    return streak


def evaluate_meta_architect_trigger(trade_count: int) -> dict[str, Any]:
    """
    Decide minimum trades required for this cycle. Logs trigger rationale for trust ledger.
    Default: 100-trade floor only. Adaptive path requires FORTRESS_META_ARCHITECT_ADAPTIVE_ENABLED=1.
    """
    result = {
        "min_trades_required": MIN_TRADES_REQUIRED,
        "trade_count": trade_count,
        "trigger": "default_floor",
        "early_trigger": False,
        "inputs": {},
    }
    if trade_count >= MIN_TRADES_REQUIRED:
        return result
    if not _adaptive_meta_enabled():
        return result

    drift_alert = False
    try:
        drift = json.loads((Path("data") / "drift_report.json").read_text(encoding="utf-8"))
        drift_alert = bool((drift or {}).get("drift_alert"))
        result["inputs"]["drift_alert"] = drift_alert
        result["inputs"]["drift_reason"] = (drift or {}).get("reason")
    except Exception:
        drift_alert = False

    gap_streak = _fortress_capability_gap_streak()
    result["inputs"]["capability_gap_streak"] = gap_streak
    floor = _early_trade_floor()
    need_gaps = _gap_cycles_required()

    if (
        drift_alert
        and trade_count >= floor
        and gap_streak >= need_gaps
    ):
        result["min_trades_required"] = floor
        result["trigger"] = "adaptive_early"
        result["early_trigger"] = True
    return result


def _log_meta_architect_trigger(trigger: dict[str, Any]) -> None:
    try:
        from utils.trust_ledger import append_trust_event

        append_trust_event(
            "meta_architect_trigger",
            {
                "trigger": trigger.get("trigger"),
                "early_trigger": trigger.get("early_trigger"),
                "trade_count": trigger.get("trade_count"),
                "min_trades_required": trigger.get("min_trades_required"),
                "inputs": trigger.get("inputs"),
            },
        )
    except Exception:
        pass


def analyze_performance_gaps(lookback_days=LOOKBACK_DAYS):
    """
    Analyze last N days of trades to identify performance gaps.
    
    Uses configured LLM (DeepSeek) to identify patterns in losses:
    - Sector-specific losses
    - Volatility-related losses
    - Early exits
    - Missed opportunities
    
    Args:
        lookback_days: Number of days to analyze
        
    Returns:
        dict: {
            'total_trades': int,
            'win_rate': float,
            'losses': list of loss trades,
            'patterns': list of identified patterns,
            'suggested_agents': list of agent suggestions
        }
    """
    logger.info("=" * 80)
    logger.info("ANALYZING PERFORMANCE GAPS")
    logger.info("=" * 80)
    
    try:
        # Load trades from decisions log
        trades = load_recent_trades(lookback_days)
        trigger = evaluate_meta_architect_trigger(len(trades))
        _log_meta_architect_trigger(trigger)
        min_required = int(trigger.get("min_trades_required") or MIN_TRADES_REQUIRED)
        
        if len(trades) < min_required:
            logger.warning(f"Insufficient trades: {len(trades)} < {min_required}")
            return {
                'total_trades': len(trades),
                'error': f'Need at least {min_required} trades for analysis',
                'meta_architect_trigger': trigger,
                'suggested_agents': []
            }
        
        logger.info(f"Analyzing {len(trades)} trades from last {lookback_days} days")
        
        # Separate wins and losses
        wins = [t for t in trades if t.get('outcome') == 'WIN']
        losses = [t for t in trades if t.get('outcome') == 'LOSS']
        
        win_rate = len(wins) / len(trades) if trades else 0
        
        logger.info(f"Win rate: {win_rate*100:.1f}% ({len(wins)} wins, {len(losses)} losses)")
        
        # Analyze loss patterns
        loss_patterns = analyze_loss_patterns(losses)
        
        # Use LLM to identify weaknesses
        llm_analysis = get_llm_weakness_analysis(trades, wins, losses, loss_patterns)
        
        # Combine patterns
        all_patterns = loss_patterns + llm_analysis.get('patterns', [])
        
        # Generate agent suggestions
        suggested_agents = generate_agent_suggestions(all_patterns, llm_analysis)
        
        result = {
            'timestamp': datetime.now().isoformat(),
            'lookback_days': lookback_days,
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'loss_patterns': loss_patterns,
            'llm_analysis': llm_analysis,
            'suggested_agents': suggested_agents
        }
        
        logger.info(f"Found {len(suggested_agents)} agent suggestions")
        
        return result
        
    except Exception as e:
        logger.error(f"Error analyzing performance gaps: {type(e).__name__}: {str(e)}")
        return {
            'error': str(e),
            'suggested_agents': []
        }


def load_recent_trades(lookback_days):
    """
    Load trades from decisions_log.jsonl for the last N days.
    
    Args:
        lookback_days: Number of days to look back
        
    Returns:
        list: List of trade dicts with outcomes
    """
    if not DECISIONS_LOG.exists():
        logger.warning(f"Decisions log not found: {DECISIONS_LOG}")
        return []
    
    cutoff_date = datetime.now() - timedelta(days=lookback_days)
    trades = []
    
    try:
        with open(DECISIONS_LOG, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    
                    # Parse timestamp
                    timestamp = datetime.fromisoformat(entry.get('timestamp', ''))
                    
                    if timestamp >= cutoff_date:
                        trades.append(entry)
                        
                except json.JSONDecodeError:
                    continue
                except ValueError:
                    continue
        
        logger.info(f"Loaded {len(trades)} trades from {DECISIONS_LOG}")
        return trades
        
    except Exception as e:
        logger.error(f"Error loading trades: {type(e).__name__}: {str(e)}")
        return []


def analyze_loss_patterns(losses):
    """
    Analyze patterns in losing trades.
    
    Args:
        losses: List of losing trades
        
    Returns:
        list: List of pattern dicts
    """
    patterns = []
    
    if not losses:
        return patterns
    
    # Analyze by sector
    sector_losses = defaultdict(list)
    for loss in losses:
        sector = loss.get('sector', 'Unknown')
        sector_losses[sector].append(loss)
    
    # Find sectors with high loss rate
    for sector, sector_trades in sector_losses.items():
        if len(sector_trades) >= 3:  # At least 3 losses in sector
            patterns.append({
                'type': 'sector_weakness',
                'sector': sector,
                'loss_count': len(sector_trades),
                'description': f'High losses in {sector} sector ({len(sector_trades)} trades)'
            })
    
    # Analyze by volatility
    high_volatility_losses = [l for l in losses if l.get('metrics', {}).get('volatility', 0) > 0.03]
    if len(high_volatility_losses) >= 5:
        patterns.append({
            'type': 'volatility_weakness',
            'loss_count': len(high_volatility_losses),
            'description': f'High losses on volatile stocks ({len(high_volatility_losses)} trades)'
        })
    
    # Analyze exit timing
    early_exits = [l for l in losses if l.get('exit_reason') == 'stop_loss' and l.get('hold_days', 0) < 2]
    if len(early_exits) >= 5:
        patterns.append({
            'type': 'early_exit',
            'loss_count': len(early_exits),
            'description': f'Frequent early stop-loss exits ({len(early_exits)} trades)'
        })
    
    # Analyze RSI levels
    low_rsi_losses = [l for l in losses if l.get('metrics', {}).get('rsi', 100) < 25]
    if len(low_rsi_losses) >= 5:
        patterns.append({
            'type': 'oversold_weakness',
            'loss_count': len(low_rsi_losses),
            'description': f'Losses on extremely oversold stocks ({len(low_rsi_losses)} trades)'
        })
    
    logger.info(f"Identified {len(patterns)} loss patterns")
    return patterns


def get_llm_weakness_analysis(trades, wins, losses, loss_patterns):
    """
    Use LOCAL Llama to analyze trading patterns and identify weaknesses.
    
    Args:
        trades: All trades
        wins: Winning trades
        losses: Losing trades
        loss_patterns: Pre-identified patterns
        
    Returns:
        dict: LLM analysis with patterns and suggestions
    """
    logger.info("Requesting Llama analysis of trading patterns...")
    
    # Prepare summary for Llama
    summary = {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) if trades else 0,
        'loss_patterns': loss_patterns,
        'sample_losses': losses[:10]  # First 10 losses
    }
    
    prompt = f"""Analyze these trading results and identify 3 specific weaknesses:

Trading Summary:
- Total trades: {summary['total_trades']}
- Win rate: {summary['win_rate']*100:.1f}%
- Wins: {summary['wins']}, Losses: {summary['losses']}

Loss Patterns Found:
{json.dumps(loss_patterns, indent=2)}

Sample Losing Trades:
{json.dumps(summary['sample_losses'], indent=2)}

Identify 3 specific weaknesses in the trading strategy. For each weakness:
1. Describe the problem
2. Suggest what type of agent could help
3. Estimate potential improvement

Return ONLY valid JSON in this format:
{{
  "patterns": [
    {{
      "weakness": "description",
      "agent_type": "suggested agent name",
      "potential_improvement": "percentage or description"
    }}
  ]
}}"""

    try:
        response = call_llm(prompt, timeout=90)
        
        if not response:
            logger.warning("Llama returned empty response")
            return {'patterns': []}
        
        # Parse JSON response
        # Try to extract JSON from response
        response = response.strip()
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0].strip()
        elif '```' in response:
            response = response.split('```')[1].split('```')[0].strip()
        
        analysis = json.loads(response)
        logger.info(f"Llama identified {len(analysis.get('patterns', []))} weaknesses")
        
        return analysis
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Llama response as JSON: {e}")
        logger.error(f"Response was: {response[:500]}")
        return {'patterns': []}
    except Exception as e:
        logger.error(f"Error getting Llama analysis: {type(e).__name__}: {str(e)}")
        return {'patterns': []}


def generate_agent_suggestions(patterns, llm_analysis):
    """
    Generate specific agent suggestions based on identified patterns.
    
    Args:
        patterns: List of pattern dicts
        llm_analysis: LLM analysis
        
    Returns:
        list: List of agent suggestion dicts
    """
    suggestions = []
    
    # Map patterns to agent types
    for pattern in patterns:
        pattern_type = pattern.get('type')
        
        if pattern_type == 'sector_weakness':
            suggestions.append({
                'agent_name': f"SectorFilter_{pattern['sector'].replace(' ', '')}",
                'purpose': f"Filter out or adjust sizing for {pattern['sector']} sector trades",
                'weakness_addressed': pattern['description'],
                'priority': 'HIGH' if pattern['loss_count'] >= 5 else 'MEDIUM'
            })
        
        elif pattern_type == 'volatility_weakness':
            suggestions.append({
                'agent_name': 'VolatilityGuard',
                'purpose': 'Filter high-volatility stocks or adjust position sizing',
                'weakness_addressed': pattern['description'],
                'priority': 'HIGH'
            })
        
        elif pattern_type == 'early_exit':
            suggestions.append({
                'agent_name': 'DynamicStopLoss',
                'purpose': 'Adjust stop-loss based on volatility and market conditions',
                'weakness_addressed': pattern['description'],
                'priority': 'MEDIUM'
            })
        
        elif pattern_type == 'oversold_weakness':
            suggestions.append({
                'agent_name': 'OversoldValidator',
                'purpose': 'Additional validation for extremely oversold stocks',
                'weakness_addressed': pattern['description'],
                'priority': 'MEDIUM'
            })
    
    # Add Llama suggestions
    for llm_pattern in llm_analysis.get('patterns', []):
        suggestions.append({
            'agent_name': llm_pattern.get('agent_type', 'CustomAgent').replace(' ', '_'),
            'purpose': llm_pattern.get('weakness'),
            'weakness_addressed': llm_pattern.get('weakness'),
            'potential_improvement': llm_pattern.get('potential_improvement'),
            'priority': 'HIGH',
            'source': 'llm'
        })
    
    # Remove duplicates
    unique_suggestions = []
    seen_names = set()
    
    for suggestion in suggestions:
        name = suggestion['agent_name']
        if name not in seen_names:
            unique_suggestions.append(suggestion)
            seen_names.add(name)
    
    # Sort by priority
    priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    unique_suggestions.sort(key=lambda x: priority_order.get(x.get('priority', 'LOW'), 3))
    
    return unique_suggestions


def design_new_agent(weakness_description, agent_name):
    """
    Use Llama to design agent architecture.
    
    Args:
        weakness_description: Description of weakness to address
        agent_name: Suggested name for agent
        
    Returns:
        dict: Agent blueprint or None if failed
    """
    logger.info(f"Designing agent: {agent_name}")
    
    prompt = f"""Design a Python trading agent to solve this weakness:

Weakness: {weakness_description}
Agent Name: {agent_name}

Design requirements:
- Simple and focused (max 100 lines of code)
- Use existing utils (local_llm.py, etc.)
- Input: trade candidate or position data
- Output: decision (approve/reject/adjust) with reasoning
- Include error handling and logging

Return ONLY valid JSON in this format:
{{
  "agent_name": "{agent_name}",
  "functions_needed": ["function1", "function2"],
  "data_inputs": ["input1", "input2"],
  "outputs": ["output1", "output2"],
  "logic_description": "brief description of logic",
  "integration_point": "where in workflow to use this agent"
}}"""

    try:
        response = call_llm(prompt, timeout=90)
        
        if not response:
            logger.warning("Llama returned empty response")
            return None
        
        # Parse JSON response
        response = response.strip()
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0].strip()
        elif '```' in response:
            response = response.split('```')[1].split('```')[0].strip()
        
        blueprint = json.loads(response)
        logger.info(f"Agent blueprint created: {blueprint['agent_name']}")
        
        return blueprint
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Llama response as JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error designing agent: {type(e).__name__}: {str(e)}")
        return None


def generate_agent_code(blueprint):
    """
    Use Llama to write actual Python code for the agent.
    
    Args:
        blueprint: Agent blueprint dict
        
    Returns:
        dict: {
            'success': bool,
            'file_path': Path or None,
            'code': str or None,
            'error': str or None
        }
    """
    agent_name = blueprint['agent_name']
    logger.info(f"Generating code for agent: {agent_name}")
    
    prompt = f"""Write Python code for this trading agent:

Blueprint:
{json.dumps(blueprint, indent=2)}

Requirements:
- Complete, executable Python code
- Use existing imports: logging, json, datetime, Path
- Use utils.local_llm.call_llm() if needed
- Include docstrings
- Include error handling
- Include logging statements
- Keep it under 100 lines
- Return decision dict with 'approved', 'reasoning', 'adjustments'

Return ONLY the Python code, no explanations or markdown.
Start with imports and end with the main function."""

    try:
        response = call_llm(prompt, timeout=120)
        
        if not response:
            logger.warning("Llama returned empty response")
            return {'success': False, 'error': 'Empty response from Llama'}
        
        # Clean up response
        code = response.strip()
        if '```python' in code:
            code = code.split('```python')[1].split('```')[0].strip()
        elif '```' in code:
            code = code.split('```')[1].split('```')[0].strip()
        
        # Save to file
        file_name = f"generated_{agent_name.lower()}.py"
        file_path = GENERATED_AGENTS_DIR / file_name
        
        with open(file_path, 'w') as f:
            f.write(code)
        
        logger.info(f"Agent code saved to {file_path}")
        
        # Add to git
        try:
            subprocess.run(['git', 'add', str(file_path)], check=True, capture_output=True)
            commit_msg = f"[Meta-Architect] Generated agent: {agent_name}"
            subprocess.run(['git', 'commit', '-m', commit_msg], check=True, capture_output=True)
            logger.info(f"Agent committed to git: {commit_msg}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to commit to git: {e}")
        
        return {
            'success': True,
            'file_path': file_path,
            'code': code,
            'error': None
        }
        
    except Exception as e:
        logger.error(f"Error generating agent code: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'file_path': None,
            'code': None,
            'error': str(e)
        }


def test_new_agent(agent_file, test_days=10):
    """
    Test new agent on historical data (backtest).
    
    Args:
        agent_file: Path to agent file
        test_days: Number of days to backtest
        
    Returns:
        dict: {
            'success': bool,
            'improvement': float (percentage),
            'baseline_win_rate': float,
            'agent_win_rate': float,
            'keep_agent': bool,
            'error': str or None
        }
    """
    logger.info(f"Testing agent: {agent_file}")
    
    try:
        # Load the agent module
        spec = importlib.util.spec_from_file_location("test_agent", agent_file)
        agent_module = importlib.util.module_from_spec(spec)
        sys.modules["test_agent"] = agent_module
        spec.loader.exec_module(agent_module)
        
        # Load test data
        test_trades = load_recent_trades(test_days)
        
        if len(test_trades) < 10:
            logger.warning(f"Insufficient test data: {len(test_trades)} trades")
            return {
                'success': False,
                'error': 'Insufficient test data',
                'keep_agent': False
            }
        
        # Calculate baseline win rate
        baseline_wins = len([t for t in test_trades if t.get('outcome') == 'WIN'])
        baseline_win_rate = baseline_wins / len(test_trades)
        
        # Test agent on each trade
        agent_approved = []
        for trade in test_trades:
            try:
                # Try to call agent's main function
                # This is a simplified test - real implementation would need agent-specific logic
                if hasattr(agent_module, 'evaluate'):
                    result = agent_module.evaluate(trade)
                    if result.get('approved', True):
                        agent_approved.append(trade)
                else:
                    # If no evaluate function, assume agent approves all
                    agent_approved.append(trade)
            except Exception as e:
                logger.warning(f"Error testing trade with agent: {e}")
                agent_approved.append(trade)  # Default to approve
        
        # Calculate agent win rate
        agent_wins = len([t for t in agent_approved if t.get('outcome') == 'WIN'])
        agent_win_rate = agent_wins / len(agent_approved) if agent_approved else 0
        
        # Calculate improvement
        improvement = (agent_win_rate - baseline_win_rate) / baseline_win_rate if baseline_win_rate > 0 else 0
        
        keep_agent = improvement >= IMPROVEMENT_THRESHOLD
        
        logger.info(f"Test results: Baseline {baseline_win_rate*100:.1f}%, Agent {agent_win_rate*100:.1f}%, Improvement {improvement*100:.1f}%")
        logger.info(f"Decision: {'KEEP' if keep_agent else 'DELETE'}")
        
        return {
            'success': True,
            'improvement': improvement,
            'baseline_win_rate': baseline_win_rate,
            'agent_win_rate': agent_win_rate,
            'trades_tested': len(test_trades),
            'trades_approved': len(agent_approved),
            'keep_agent': keep_agent,
            'error': None
        }
        
    except Exception as e:
        logger.error(f"Error testing agent: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'keep_agent': False
        }


def autonomous_improvement_cycle():
    """
    Run complete autonomous improvement cycle.
    
    Steps:
    1. Analyze performance gaps
    2. Design 1-2 new agents
    3. Generate code
    4. Test on historical data
    5. Keep winners, delete losers
    
    Returns:
        dict: Report of cycle results
    """
    logger.info("=" * 80)
    logger.info("STARTING AUTONOMOUS IMPROVEMENT CYCLE")
    logger.info("=" * 80)
    
    start_time = datetime.now()
    
    try:
        # Check agent limit
        existing_agents = list(GENERATED_AGENTS_DIR.glob("generated_*.py"))
        if len(existing_agents) >= MAX_GENERATED_AGENTS:
            logger.warning(f"Agent limit reached: {len(existing_agents)}/{MAX_GENERATED_AGENTS}")
            return {
                'success': False,
                'error': f'Maximum generated agents limit reached ({MAX_GENERATED_AGENTS})',
                'agents_created': 0
            }
        
        # Step 1: Analyze performance gaps
        logger.info("Step 1: Analyzing performance gaps...")
        analysis = analyze_performance_gaps()
        
        if 'error' in analysis:
            logger.error(f"Analysis failed: {analysis['error']}")
            return {
                'success': False,
                'error': analysis['error'],
                'agents_created': 0
            }
        
        suggestions = analysis.get('suggested_agents', [])
        
        if not suggestions:
            logger.info("No agent suggestions generated")
            return {
                'success': True,
                'agents_created': 0,
                'message': 'No weaknesses requiring new agents'
            }
        
        # Limit to top 2 suggestions
        suggestions = suggestions[:2]
        
        agents_created = []
        agents_failed = []
        
        for suggestion in suggestions:
            agent_name = suggestion['agent_name']
            weakness = suggestion['weakness_addressed']
            
            logger.info(f"\nProcessing suggestion: {agent_name}")
            
            # Step 2: Design agent
            logger.info("Step 2: Designing agent architecture...")
            blueprint = design_new_agent(weakness, agent_name)
            
            if not blueprint:
                logger.error(f"Failed to design agent: {agent_name}")
                agents_failed.append({
                    'agent_name': agent_name,
                    'stage': 'design',
                    'error': 'Blueprint generation failed'
                })
                continue
            
            # Step 3: Generate code
            logger.info("Step 3: Generating agent code...")
            code_result = generate_agent_code(blueprint)
            
            if not code_result['success']:
                logger.error(f"Failed to generate code: {agent_name}")
                agents_failed.append({
                    'agent_name': agent_name,
                    'stage': 'code_generation',
                    'error': code_result['error']
                })
                continue
            
            # Step 4: Test agent
            logger.info("Step 4: Testing agent on historical data...")
            test_result = test_new_agent(code_result['file_path'])
            
            if not test_result['success']:
                logger.error(f"Failed to test agent: {agent_name}")
                agents_failed.append({
                    'agent_name': agent_name,
                    'stage': 'testing',
                    'error': test_result['error']
                })
                # Delete failed agent
                if code_result['file_path'].exists():
                    code_result['file_path'].unlink()
                    logger.info(f"Deleted failed agent: {code_result['file_path']}")
                continue
            
            # Step 5: Keep or delete based on performance
            if test_result['keep_agent']:
                logger.info(f"✓ Agent KEPT: {agent_name} (improvement: {test_result['improvement']*100:.1f}%)")
                agents_created.append({
                    'agent_name': agent_name,
                    'file_path': str(code_result['file_path']),
                    'improvement': test_result['improvement'],
                    'baseline_win_rate': test_result['baseline_win_rate'],
                    'agent_win_rate': test_result['agent_win_rate'],
                    'weakness_addressed': weakness
                })
            else:
                logger.info(f"✗ Agent DELETED: {agent_name} (improvement: {test_result['improvement']*100:.1f}%)")
                # Delete agent
                if code_result['file_path'].exists():
                    code_result['file_path'].unlink()
                    logger.info(f"Deleted underperforming agent: {code_result['file_path']}")
                agents_failed.append({
                    'agent_name': agent_name,
                    'stage': 'performance',
                    'improvement': test_result['improvement'],
                    'reason': 'Below improvement threshold'
                })
        
        # Compile results
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        result = {
            'success': True,
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'analysis': analysis,
            'agents_created': agents_created,
            'agents_failed': agents_failed,
            'total_created': len(agents_created),
            'total_failed': len(agents_failed)
        }
        
        logger.info("=" * 80)
        logger.info(f"IMPROVEMENT CYCLE COMPLETE: {len(agents_created)} agents created, {len(agents_failed)} failed")
        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info("=" * 80)
        
        # Save report
        save_improvement_report(result)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in improvement cycle: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'agents_created': 0
        }


def save_improvement_report(result):
    """
    Save improvement cycle report to file.
    
    Args:
        result: Result dict from autonomous_improvement_cycle()
    """
    try:
        date_str = datetime.now().strftime('%Y%m%d')
        filename = DATA_DIR / f"improvement_report_{date_str}.json"
        
        with open(filename, 'w') as f:
            json.dump(result, f, indent=2)
        
        logger.info(f"Improvement report saved to {filename}")
        
    except Exception as e:
        logger.error(f"Error saving improvement report: {type(e).__name__}: {str(e)}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python meta_architect.py analyze    - Analyze performance gaps")
        print("  python meta_architect.py cycle      - Run full improvement cycle")
        print("  python meta_architect.py test FILE  - Test specific agent file")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "analyze":
        print("\nAnalyzing performance gaps...")
        result = analyze_performance_gaps()
        
        print("\n" + "=" * 80)
        print("PERFORMANCE GAP ANALYSIS")
        print("=" * 80)
        print(f"Total trades: {result.get('total_trades', 0)}")
        print(f"Win rate: {result.get('win_rate', 0)*100:.1f}%")
        
        if result.get('suggested_agents'):
            print(f"\nSuggested Agents ({len(result['suggested_agents'])}):")
            for i, agent in enumerate(result['suggested_agents'], 1):
                print(f"\n{i}. {agent['agent_name']}")
                print(f"   Purpose: {agent['purpose']}")
                print(f"   Priority: {agent.get('priority', 'MEDIUM')}")
        else:
            print("\nNo agent suggestions generated")
    
    elif command == "cycle":
        print("\nRunning autonomous improvement cycle...")
        result = autonomous_improvement_cycle()
        
        print("\n" + "=" * 80)
        print("IMPROVEMENT CYCLE RESULTS")
        print("=" * 80)
        print(f"Success: {result['success']}")
        print(f"Agents created: {result.get('total_created', 0)}")
        print(f"Agents failed: {result.get('total_failed', 0)}")
        
        if result.get('agents_created'):
            print("\nCreated Agents:")
            for agent in result['agents_created']:
                print(f"\n  {agent['agent_name']}")
                print(f"    File: {agent['file_path']}")
                print(f"    Improvement: {agent['improvement']*100:.1f}%")
                print(f"    Addresses: {agent['weakness_addressed']}")
    
    elif command == "test":
        if len(sys.argv) < 3:
            print("Usage: python meta_architect.py test FILE")
            sys.exit(1)
        
        agent_file = Path(sys.argv[2])
        if not agent_file.exists():
            print(f"Error: File not found: {agent_file}")
            sys.exit(1)
        
        print(f"\nTesting agent: {agent_file}")
        result = test_new_agent(agent_file)
        
        print("\n" + "=" * 80)
        print("AGENT TEST RESULTS")
        print("=" * 80)
        print(f"Success: {result['success']}")
        
        if result['success']:
            print(f"Baseline win rate: {result['baseline_win_rate']*100:.1f}%")
            print(f"Agent win rate: {result['agent_win_rate']*100:.1f}%")
            print(f"Improvement: {result['improvement']*100:.1f}%")
            print(f"Decision: {'KEEP' if result['keep_agent'] else 'DELETE'}")
        else:
            print(f"Error: {result['error']}")
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
