"""
Trading System Orchestrator
Coordinates the complete workflow: screening, entry evaluation, risk management, and position monitoring
"""

import os
from pathlib import Path

# Agents configure logging with relative `logs/...` paths; align cwd before those imports.
_ORCHESTRATOR_ROOT = Path(__file__).resolve().parent
os.chdir(_ORCHESTRATOR_ROOT)
(_ORCHESTRATOR_ROOT / "logs").mkdir(parents=True, exist_ok=True)

import asyncio
import json
import logging
import threading
import glob
import time
import time as pytime
from datetime import datetime, time, timedelta, timezone
from dateutil import parser
from collections import Counter
import pytz
from dotenv import load_dotenv

# Import Alpaca
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

# Import agents
from agents.screener_agent import run_screener
from agents.entry_agent import evaluate_entry
from agents.exit_monitor import monitor_positions as monitor_exit_conditions
from agents.risk_guardian import check_risk_limits, get_risk_limits, get_risk_status, update_consecutive_losses
from agents.performance_analyzer import track_decision, track_outcome, load_current_params
from utils.llm_decision_tracker import get_llm_decision_tracker
from agents.llm_learning_agent import LLMLearningAgent
from agents.llama_watchdog import run_watchdog, preload_models, is_emergency_mode
# Fortress hedging is optionally deployable; avoid import-time failures.
# We import it lazily inside `run_fortress()` so `orchestrator.py` can start
# even if some hedge dependencies are missing.
from agents.document_analyst import quick_fundamental_check
from agents.intraday_sniper import scan_intraday_opportunities, evaluate_quick_entry
from agents.spy_intraday_swing import run_spy_swing_cycle
from agents.day_trading_manager import DayTradingManager
from agents.swing_trading_manager import SwingTradingManager
from agents.position_trading_manager import PositionTradingManager
from agents.sector_rotation_manager import run_sector_rotation_manager
from agents.geographic_allocation_manager import run_geographic_allocation_manager
from agents.sector_executor import run_sector_rotation_execution
from agents.geographic_executor import run_geographic_allocation_execution
from agents.cio_agent import run_cio_cycle
from agents.scouts.swarm import run_scout_swarm
from agents.analysts.consensus import run_analyst_ensemble
from agents.intelligence_brief_generator import generate_brief, generate_markdown_summary
from agents.recursive_evolution import run_recursive_evolution
from utils.grok_sentiment import check_twitter_sentiment
from utils.option_contract_schema import normalize_option_decision
from utils.policy_profile import get_profile_bundle
from utils.trust_ledger import append_trust_event
from utils.run_registry import (
    log_screening_completed,
    log_screening_failed,
    log_screening_started,
)
from utils.smart_execution import build_execution_plan
from utils.pre_trade_gate import evaluate_pre_trade_submission, format_gate_block_message
from utils.runtime_config import (
    get_default_portfolio_usd,
    get_spy_swing_default_equity_usd,
    is_agent_enabled,
)
from utils.strategy_allocation import load_strategy_allocation_config
from utils.cost_calculator import (
    get_daily_costs,
    get_monthly_projection,
    get_lifetime_costs,
    get_cost_per_trade,
    generate_cost_report
)
from utils.execution_mode import get_execution_mode


def _order_is_filled(order_result: dict) -> bool:
    """
    Create/persist positions only after a filled order.
    This prevents ghost positions from orders that were only accepted.
    """
    status = str(order_result.get("status", "")).strip().lower()
    filled_price = order_result.get("filled_price")
    status_filled = status == "filled" or status.endswith(".filled")
    return status_filled and filled_price is not None


def _load_latest_fortress_report(max_age_hours=None):
    """Load newest fortress_report_*.json if present, with freshness metadata."""
    meta = {"path": None, "age_hours": None, "is_fresh": None}
    try:
        fort_pattern = DATA_DIR / "fortress_report_*.json"
        fort_files = sorted(glob.glob(str(fort_pattern)), reverse=True)
        if not fort_files:
            return None, meta
        latest_fort_path = Path(fort_files[0])
        meta["path"] = str(latest_fort_path)
        age_hours = (pytime.time() - latest_fort_path.stat().st_mtime) / 3600.0
        meta["age_hours"] = round(age_hours, 2)
        meta["is_fresh"] = True if max_age_hours is None else age_hours <= float(max_age_hours)
        with open(latest_fort_path, "r") as f:
            return json.load(f), meta
    except Exception:
        return None, meta


def _read_latest_json(data_dir: Path, filename_glob: str) -> dict:
    """
    Read latest JSON file matching {filename_glob} under data_dir.
    Returns an empty dict when no match or on JSON errors.
    """
    try:
        pattern = data_dir / filename_glob
        paths = sorted(glob.glob(str(pattern)), reverse=True)
        if not paths:
            return {}
        latest_path = Path(paths[0])
        doc = json.loads(latest_path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _refresh_order_result(order_result: dict, max_wait_seconds: int = 3, poll_interval_seconds: float = 1.0) -> dict:
    """
    Best-effort refresh from Alpaca when submit returns ACCEPTED/PENDING_NEW.
    Prevents prematurely marking exits as executed before actual fill.
    """
    if not isinstance(order_result, dict):
        return order_result
    if not order_result.get("success"):
        return order_result
    if _order_is_filled(order_result):
        return order_result

    order_id = order_result.get("order_id")
    if not order_id or alpaca_client is None:
        return order_result

    deadline = pytime.time() + max_wait_seconds
    while pytime.time() < deadline:
        try:
            order = alpaca_client.get_order_by_id(order_id)
            order_result["status"] = str(getattr(order, "status", order_result.get("status")))
            order_result["filled_qty"] = int(order.filled_qty) if getattr(order, "filled_qty", None) else None
            order_result["filled_price"] = float(order.filled_avg_price) if getattr(order, "filled_avg_price", None) else None
            if _order_is_filled(order_result):
                break
        except Exception:
            break
        pytime.sleep(poll_interval_seconds)
    return order_result


def _read_pnl_ledger_order_ids() -> set[str]:
    """Return set of already-recorded order_ids in pnl_ledger.jsonl."""
    order_ids: set[str] = set()
    if not PNL_LEDGER_FILE.exists():
        return order_ids
    try:
        with open(PNL_LEDGER_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                oid = rec.get("order_id")
                if oid:
                    order_ids.add(str(oid))
    except Exception:
        pass
    return order_ids


def _append_pnl_ledger_once(entry: dict, seen_order_ids: set[str]) -> bool:
    """Append one PnL ledger entry once per order_id."""
    order_id = entry.get("order_id")
    if order_id and str(order_id) in seen_order_ids:
        return False
    try:
        PNL_LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PNL_LEDGER_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        if order_id:
            seen_order_ids.add(str(order_id))
        return True
    except Exception:
        return False


def _derive_entry_price_from_signal(signal: dict, filled_price: float) -> float | None:
    """
    Derive entry price when original position is no longer present.
    Uses pnl_pct relationship: filled = entry * (1 + pnl_pct).
    """
    try:
        pnl_pct = signal.get("pnl_pct")
        if pnl_pct is None:
            return None
        pnl_pct = float(pnl_pct)
        denom = 1.0 + pnl_pct
        if abs(denom) < 1e-9:
            return None
        return float(filled_price) / denom
    except Exception:
        return None


def _compute_hedge_gate_metrics_from_report(report: dict) -> dict:
    """
    Compute hedge gate metrics from the latest fortress report.

    Gate pass rule (risk elimination):
      passed iff (applied_count >= 1) OR (bonds_target_present).
    """
    known_strategies = [
        "bonds",
        "commodities",
        "forex",
        "vix_insurance",
        "theta_spreads",
        "dividend_capture",
        "pairs_trading",
    ]

    strategies = report.get("strategies") or {}
    applied = 0
    skipped = 0
    not_evaluated = 0
    bonds_target_present = False

    strategy_gate_details = {}

    for name in known_strategies:
        s = strategies.get(name)
        if not isinstance(s, dict):
            not_evaluated += 1
            strategy_gate_details[name] = {"status": "not_evaluated"}
            continue

        if name == "bonds":
            target = s.get("target")
            bonds_target_present = target is not None
            if bonds_target_present:
                applied += 1
                strategy_gate_details[name] = {"status": "applied", "target": target}
            else:
                skipped += 1
                strategy_gate_details[name] = {"status": "skipped", "target": target}
            continue

        action = s.get("action")
        reason = s.get("reason") or s.get("opportunity") or ""
        action_upper = str(action).upper() if action is not None else None

        if action is None:
            not_evaluated += 1
            strategy_gate_details[name] = {"status": "not_evaluated", "action": action, "reason": reason}
        elif action_upper in ["SKIP", "NONE", "HOLD"]:
            skipped += 1
            strategy_gate_details[name] = {"status": "skipped", "action": action, "reason": reason}
        else:
            applied += 1
            strategy_gate_details[name] = {"status": "applied", "action": action, "reason": reason}

    passed = (applied >= 1) or bool(bonds_target_present)

    return {
        "passed": passed,
        "applied_count": applied,
        "skipped_count": skipped,
        "not_evaluated_count": not_evaluated,
        "bonds_target_present": bonds_target_present,
        "total_known": len(known_strategies),
        "strategy_gate_details": strategy_gate_details,
    }

# Repo-root paths: logs/data/.env (cwd already set to repo root above).
load_dotenv(_ORCHESTRATOR_ROOT / ".env")

# Setup logging
log_dir = _ORCHESTRATOR_ROOT / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

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
DATA_DIR = _ORCHESTRATOR_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def verify_learning() -> dict:
    """
    Report DeepSeek/LLM config, recursive-learning artifacts (llm_decisions / llm_lessons),
    and cost telemetry. JSON-serializable for dashboards/scripts.
    """
    from utils.runtime_config import get_llm_config

    cfg = get_llm_config() or {}
    provider = str(cfg.get("provider") or "none").strip().lower()
    deepseek_model = str(cfg.get("deepseek_model") or cfg.get("default_model") or "").strip()

    def _file_info(path: Path) -> dict:
        out = {"path": str(path), "exists": path.exists(), "lines": 0, "last_timestamp": None}
        if not path.exists():
            return out
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            nonempty = [ln for ln in lines if ln.strip()]
            out["lines"] = len(nonempty)
            if nonempty:
                try:
                    last = json.loads(nonempty[-1])
                    out["last_timestamp"] = last.get("timestamp") or last.get("outcome_timestamp")
                except Exception:
                    out["last_timestamp"] = "parse_error"
        except OSError as e:
            out["error"] = str(e)
        return out

    decisions = _file_info(DATA_DIR / "llm_decisions.jsonl")
    lessons = _file_info(DATA_DIR / "llm_lessons.jsonl")
    api_costs = _file_info(DATA_DIR / "api_costs.jsonl")

    return {
        "timestamp": datetime.now().isoformat(),
        "llm": {
            "provider": provider,
            "deepseek_model": deepseek_model or None,
            "entry_min_confidence": float(os.getenv("FORTRESS_LLM_ENTRY_MIN_CONFIDENCE", "0.55")),
            "learning_on_exit": str(os.getenv("FORTRESS_LLM_LEARNING_ON_EXIT", "1")).strip().lower()
            in {"1", "true", "yes", "on"},
        },
        "artifacts": {
            "llm_decisions_jsonl": decisions,
            "llm_lessons_jsonl": lessons,
            "api_costs_jsonl": api_costs,
        },
        "integration": {
            "entry_eval": "agents/entry_agent.py → LLMReasoningEngine.evaluate_trade_opportunity → utils/local_llm.call_llm",
            "exit_eval": "agents/exit_monitor.py → LLMReasoningEngine.evaluate_exit (+ call_llm for news)",
            "screener_drop": "agents/screener_agent.py → analyze_stock_drop → call_llm",
            "learning_lesson": "agents/llm_learning_agent.py → call_llm; orchestrator links signal_id on BUY + outcome on SELL_ALL",
            "evolve": "orchestrator.py evolve → recursive_evolution + llm_learning_review",
        },
        "hints": [
            "llm_decisions.jsonl is created on first LLM entry evaluation (screen → entry gate with provider≠none).",
            "llm_lessons.jsonl appears after a full position exit (SELL_ALL) with signal_id on the position, or after evolve batch review.",
            "If files stay empty: confirm config/fortress_runtime.yaml llm.provider is deepseek (or ollama), DEEPSEEK_API_KEY set, and run a weekday screen during/after RTH for candidates.",
        ],
    }


POSITIONS_FILE = DATA_DIR / "positions.json"
PNL_LEDGER_FILE = DATA_DIR / "pnl_ledger.jsonl"
FORTRESS_REPORT_MAX_AGE_HOURS = float(os.getenv("FORTRESS_REPORT_MAX_AGE_HOURS", "30"))
PORTFOLIO_VALUE = get_default_portfolio_usd()  # Screening default; override via CLI or env

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
        est = float(shares) * float(entry_price or 0)
    except Exception:
        est = 0.0
    gate = evaluate_pre_trade_submission(
        side="BUY",
        symbol=ticker,
        qty=float(shares),
        estimated_notional_usd=est if est > 0 else None,
    )
    if not gate["allowed"]:
        logger.warning(f"{ticker}: pre_trade_gate blocked: {gate.get('reasons')}")
        append_trust_event(
            "pre_trade_gate_blocked",
            {"ticker": ticker, "pattern": "stock_buy", "gate": gate},
        )
        return {
            "success": False,
            "order_id": None,
            "filled_qty": None,
            "filled_price": None,
            "error": format_gate_block_message(gate),
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

    gate = evaluate_pre_trade_submission(
        side="SELL",
        symbol=ticker,
        qty=float(shares),
        estimated_notional_usd=None,
    )
    if not gate["allowed"]:
        logger.warning(f"{ticker}: pre_trade_gate blocked: {gate.get('reasons')}")
        append_trust_event(
            "pre_trade_gate_blocked",
            {"ticker": ticker, "pattern": "stock_sell", "gate": gate},
        )
        return {
            "success": False,
            "order_id": None,
            "filled_qty": None,
            "filled_price": None,
            "error": format_gate_block_message(gate),
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


async def submit_approved_screening_trade(trade, candidates, current_params):
    """
    Submit one approved entry from daily screening (stock or option) and persist position if filled.
    Used for autonomous execution and for ``execute_pending`` (human-in-the-loop flush).
    """
    option_symbol = None
    if trade.get("trade_type") == "OPTION" or trade.get("type") == "OPTION":
        ticker = trade["ticker"]
        strike = trade["strike"]
        expiration = trade["expiration"]
        contracts = trade["contracts"]
        call = trade.get("call", True)

        option_symbol = format_option_symbol(ticker, expiration, strike, call)
        logger.info(f"Executing OPTION order: {option_symbol} x {contracts} contracts")

        # Smart execution: prefer LIMIT for options when we have an expected entry premium.
        exec_plan = build_execution_plan(trade, market_open=True)

        if not alpaca_client:
            order_result = {
                "success": False,
                "order_id": None,
                "filled_qty": None,
                "filled_price": None,
                "error": "Alpaca client not initialized",
            }
        else:
            gate = evaluate_pre_trade_submission(
                side="BUY",
                symbol=option_symbol,
                qty=float(contracts),
                order_class="option",
                estimated_notional_usd=None,
            )
            if not gate["allowed"]:
                append_trust_event(
                    "pre_trade_gate_blocked",
                    {
                        "ticker": option_symbol,
                        "pattern": "option_buy",
                        "gate": gate,
                    },
                )
                order_result = {
                    "success": False,
                    "order_id": None,
                    "filled_qty": None,
                    "filled_price": None,
                    "error": format_gate_block_message(gate),
                }
            else:
                try:
                    if exec_plan.get("order_type") == "limit" and exec_plan.get("limit_price") is not None:
                        order_data = LimitOrderRequest(
                            symbol=option_symbol,
                            qty=contracts,
                            side=OrderSide.BUY,
                            limit_price=exec_plan["limit_price"],
                            time_in_force=TimeInForce.DAY,
                        )
                    else:
                        order_data = MarketOrderRequest(
                            symbol=option_symbol,
                            qty=contracts,
                            side=OrderSide.BUY,
                            time_in_force=TimeInForce.DAY,
                        )
                    order = alpaca_client.submit_order(order_data)
                    order_result = {
                        "success": True,
                        "order_id": str(order.id),
                        "filled_qty": int(order.filled_qty) if order.filled_qty else None,
                        "filled_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                        "status": str(order.status),
                        "error": None,
                    }
                except Exception as e:
                    order_result = {
                        "success": False,
                        "order_id": None,
                        "filled_qty": None,
                        "filled_price": None,
                        "error": f"{type(e).__name__}: {str(e)}",
                    }

    else:
        ticker = trade["ticker"]
        shares = trade["shares"]
        entry_price = trade["entry_price"]
        logger.info(f"Executing STOCK order: {ticker} x {shares} shares")

        order_result = await asyncio.to_thread(execute_buy_order, ticker, shares, entry_price)
        order_result = _refresh_order_result(order_result)

    if order_result["success"] and _order_is_filled(order_result):
        label = option_symbol or trade.get("ticker") or "?"
        logger.info(f"{label}: Order executed successfully - ID: {order_result['order_id']}")

        trade["order_id"] = order_result["order_id"]
        trade["order_status"] = order_result["status"]
        trade["filled_qty"] = order_result["filled_qty"]
        trade["filled_price"] = order_result["filled_price"]
        trade["executed"] = True
        trade["execution_time"] = datetime.now().isoformat()

        if trade.get("trade_type") == "OPTION" or trade.get("type") == "OPTION":
            await asyncio.to_thread(
                add_position,
                {
                    "ticker": option_symbol,
                    "type": "OPTION",
                    "underlying_ticker": trade["ticker"],
                    "qty": trade["contracts"],
                    "entry_premium": trade.get("filled_price") or trade.get("entry_price", 0),
                    "expiration_date": trade["expiration"],
                    "strike": trade["strike"],
                    "call": trade.get("call", True),
                    "entry_date": datetime.now().isoformat(),
                    "order_id": order_result["order_id"],
                    "sector": get_sector_from_candidates(trade["ticker"], candidates),
                    "stop_loss_pct": current_params["stop_loss_pct"],
                    "take_profit_pct": current_params.get("take_profit_pct", 15.0),
                    "tiers_sold": {"tier1": False, "tier2": False, "tier3": False},
                    "signal_id": trade.get("signal_id"),
                    "llm_decision_id": trade.get("llm_decision_id"),
                },
            )
        else:
            await asyncio.to_thread(
                add_position,
                {
                    "ticker": trade["ticker"],
                    "shares": trade.get("shares", 0),
                    "entry_price": trade.get("entry_price", 0),
                    "entry_date": datetime.now().isoformat(),
                    "order_id": order_result["order_id"],
                    "sector": get_sector_from_candidates(trade["ticker"], candidates),
                    "stop_loss_pct": current_params["stop_loss_pct"],
                    "take_profit_pct": current_params.get("take_profit_pct", 15.0),
                    "tiers_sold": {"tier1": False, "tier2": False, "tier3": False},
                    "signal_id": trade.get("signal_id"),
                    "llm_decision_id": trade.get("llm_decision_id"),
                },
            )

        return ("success", trade)

    label = option_symbol or trade.get("ticker") or "?"
    logger.error(
        f"{label}: Order not filled or execution failed - {order_result.get('error')}"
        f" (status={order_result.get('status')}, filled_price={order_result.get('filled_price')})"
    )
    trade["executed"] = False
    trade["execution_error"] = order_result.get("error")
    return ("failure", trade)


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
    
    run_id = f"screen_{int(pytime.time())}"
    policy = get_profile_bundle()
    append_trust_event("screening_started", {
        "run_id": run_id,
        "policy_profile": policy.get("active_profile"),
        "portfolio_value": portfolio_value,
    })
    log_screening_started(
        run_id,
        policy.get("active_profile"),
        float(portfolio_value),
    )
    try:
        from utils.policy_guardrails import shadow_policy_snapshot

        shadow_snap = shadow_policy_snapshot()
        if shadow_snap:
            append_trust_event("shadow_policy_observation", {"run_id": run_id, **shadow_snap})
    except Exception:
        pass
    try:
        # Step 1: Run screener
        logger.info("Step 1: Running stock screener...")
        candidates = run_screener()
        logger.info(f"Screener found {len(candidates)} candidates")

        # Screenshot-style screening telemetry (universe size + filter rejection counts).
        # Stored by `agents.screener_agent.run_screener()` for the dashboard.
        screening_meta = {}
        try:
            meta_path = DATA_DIR / "last_screening_meta.json"
            if meta_path.exists():
                screening_meta = json.loads(meta_path.read_text())
        except Exception:
            screening_meta = {}

        # Defaults so early returns still have stable dashboard fields.
        entry_gate_summary = {
            "evaluated_candidates": len(candidates),
            "buy_count": 0,
            "skip_count": 0,
            "top_skip_reasons": []
        }
        risk_gate_summary = {
            "approved_count": 0,
            "rejected_count": 0,
            "top_rejected_reasons": []
        }
        execution_gate_summary = {
            "executed_count": 0,
            "failed_count": 0,
            "top_failure_reasons": []
        }

        # Risk-elimination mode: triggered only when the risk engine is already under stress.
        risk_status = get_risk_status()
        consecutive_losses = int(risk_status.get("consecutive_losses") or 0)
        circuit_breaker_active = bool(risk_status.get("circuit_breaker_active"))
        strict_mode = circuit_breaker_active or consecutive_losses >= 2
        if circuit_breaker_active:
            strict_mode_reason = f"circuit_breaker_active (consecutive_losses={consecutive_losses})"
        elif consecutive_losses >= 2:
            strict_mode_reason = f"consecutive_losses={consecutive_losses} >= 2"
        else:
            strict_mode_reason = "normal"

        effective_limits = get_risk_limits(strict_mode=strict_mode)
        effective_max_positions = effective_limits.get("max_positions", MAX_POSITIONS)

        hedge_gate_summary = {
            "passed": None,
            "applied_count": None,
            "skipped_count": None,
            "not_evaluated_count": None,
            "bonds_target_present": None,
            "total_known": None,
            "strategy_gate_details": None,
            "reason": "not_evaluated",
        }
        # Always attempt to compute hedge gate transparency for UI metrics.
        # Enforcement still happens only when `strict_mode` is True.
        report, report_meta = _load_latest_fortress_report(max_age_hours=FORTRESS_REPORT_MAX_AGE_HOURS)
        if report is None:
            hedge_gate_summary["reason"] = "No fortress_report_*.json found"
        elif not report_meta.get("is_fresh", True):
            age = report_meta.get("age_hours")
            hedge_gate_summary["passed"] = False if strict_mode else None
            hedge_gate_summary["reason"] = (
                f"Stale fortress report ({age}h old > {FORTRESS_REPORT_MAX_AGE_HOURS}h)"
            )
        else:
            try:
                hedge_gate_summary = _compute_hedge_gate_metrics_from_report(report)
                hedge_gate_summary["reason"] = "hedging gate derived from latest fortress_report"
            except Exception:
                hedge_gate_summary["passed"] = None
                hedge_gate_summary["reason"] = "Failed to compute hedge gate metrics from fortress report"

        # Defensive: never allow non-dict hedge_gate_summary to escape.
        # Some unexpected fortress_report payloads (or compute regressions) can yield
        # a non-dict value; this would later break `hedge_gate_summary.get("passed")`.
        if not isinstance(hedge_gate_summary, dict):
            hedge_gate_summary = {
                "passed": None,
                "applied_count": None,
                "skipped_count": None,
                "not_evaluated_count": None,
                "bonds_target_present": None,
                "total_known": None,
                "strategy_gate_details": None,
                "reason": "fortress hedge gate returned non-dict result; coerced to safe defaults",
            }

        # Attach strict/hedge gate telemetry to the daily signals screener meta.
        screening_meta["strict_mode"] = strict_mode
        screening_meta["strict_mode_reason"] = strict_mode_reason
        screening_meta["hedge_gate"] = hedge_gate_summary
        
        if len(candidates) == 0:
            logger.info("No candidates found. Ending workflow.")
            result = {
                'timestamp': datetime.now().isoformat(),
                'candidates_found': 0,
                'approved_trades': [],
                'rejected_trades': [],
                'screening_meta': screening_meta,
                'entry_gate_summary': entry_gate_summary,
                'risk_gate_summary': risk_gate_summary,
                'execution_gate_summary': execution_gate_summary,
                'risk_status': risk_status
            }
            save_daily_signals(result)
            append_trust_event("screening_completed", {
                "run_id": run_id,
                "policy_profile": policy.get("active_profile"),
                "candidates_found": 0,
                "approved_count": 0,
                "executed_count": 0,
                "rejected_count": 0,
                "strict_mode": strict_mode,
                "hedge_gate_passed": hedge_gate_summary.get("passed"),
            })
            log_screening_completed(
                run_id,
                {
                    "policy_profile": policy.get("active_profile"),
                    "candidates_found": 0,
                    "approved_count": 0,
                    "executed_count": 0,
                    "rejected_count": 0,
                    "strict_mode": strict_mode,
                    "hedge_gate_passed": hedge_gate_summary.get("passed"),
                },
            )
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
                # We create only two tasks in this workflow, so index 2 can never exist.
                if isinstance(results[1], Exception):
                    logger.error(f"{ticker}: Fundamental analysis failed: {results[1]}")
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
        
        # Step 3: Evaluate entry timing and conditions
        logger.info("Step 3: Evaluating entry conditions...")
        entry_decisions = await asyncio.to_thread(evaluate_entry, candidates, portfolio_value)
        
        # Defensive filtering: option decisions may not include an `action` field yet.
        buy_decisions = [d for d in entry_decisions if d.get('action') == 'BUY']
        skip_decisions = [d for d in entry_decisions if d.get('action') == 'SKIP']
        
        logger.info(f"Entry evaluation: {len(buy_decisions)} BUY, {len(skip_decisions)} SKIP")

        # Entry gate transparency (BUY vs SKIP with top SKIP reasons).
        skip_reason_counter = Counter(
            d.get("reason") or "Unknown"
            for d in skip_decisions
            if isinstance(d, dict)
        )
        top_skip_reasons = [
            {"reason": reason, "count": count}
            for reason, count in skip_reason_counter.most_common(6)
        ]
        entry_gate_summary = {
            "evaluated_candidates": len(entry_decisions),
            "buy_count": len(buy_decisions),
            "skip_count": len(skip_decisions),
            "top_skip_reasons": top_skip_reasons
        }
        
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
                'screening_meta': screening_meta,
                'entry_gate_summary': entry_gate_summary,
                'risk_gate_summary': risk_gate_summary,
                'execution_gate_summary': execution_gate_summary,
                'risk_status': get_risk_status()
            }
            save_daily_signals(result)
            return result
        
        # Check position limit
        if account_info['position_count'] >= effective_max_positions:
            logger.warning(f"Position limit reached: {account_info['position_count']}/{effective_max_positions}")
            logger.warning("Skipping all trades")
            result = {
                'timestamp': datetime.now().isoformat(),
                'candidates_found': len(candidates),
                'approved_trades': [],
                'rejected_trades': [{'ticker': d['ticker'], 'reason': 'Position limit reached'} for d in buy_decisions],
                'screening_meta': screening_meta,
                'entry_gate_summary': entry_gate_summary,
                'risk_gate_summary': risk_gate_summary,
                'execution_gate_summary': execution_gate_summary,
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
        effective_hedge_passed = bool(hedge_gate_summary.get("passed"))

        if strict_mode and not effective_hedge_passed:
            # Hedge/strategy gates are a hard prerequisite for entries in strict mode.
            hedge_reason = hedge_gate_summary.get("reason") or "hedge gate failed"
            logger.warning(f"Strict mode hedge gate failed; rejecting all BUYs: {hedge_reason}")
            for decision in buy_decisions:
                ticker = decision["ticker"]
                rejected_trades.append({
                    "ticker": ticker,
                    "reason": f"HEDGE_GATE_FAILED: {hedge_reason}",
                    "original_decision": decision,
                    "reject_stage": "hedge_gate",
                })
        else:
            for decision in buy_decisions:
                ticker = decision['ticker']
                logger.info(f"{ticker}: Checking risk limits...")
                
                # Check position limit
                if account_info['position_count'] + len(approved_trades) >= effective_max_positions:
                    logger.warning(f"{ticker}: Position limit would be exceeded")
                    rejected_trades.append({
                        'ticker': ticker,
                        'reason': f'Position limit ({effective_max_positions}) would be exceeded',
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
                trade_type = decision.get('trade_type', 'STOCK')
                unit_count = decision.get('shares', 0)
                if trade_type == 'OPTION' or decision.get('type') == 'OPTION':
                    # Canonicalize option decision fields to avoid schema drift.
                    try:
                        decision = normalize_option_decision(decision)
                        trade_type = 'OPTION'
                        unit_count = decision.get('contracts', 0)
                    except Exception as e:
                        logger.error(f"{ticker}: Failed to normalize option decision: {type(e).__name__}: {str(e)}")
                        rejected_trades.append({
                            'ticker': ticker,
                            'reason': f'Option decision normalization failed: {type(e).__name__}: {str(e)}',
                            'original_decision': decision
                        })
                        continue
 
                new_position = {
                    'ticker': ticker,
                    'size': unit_count,
                    'value': decision['position_size'],
                    'sector': get_sector_from_candidates(ticker, candidates)
                }
                
                # Check risk limits (async)
                risk_check = await asyncio.to_thread(check_risk_limits, portfolio_data, new_position, strict_mode=strict_mode)
                
                if risk_check['approved']:
                    logger.info(f"{ticker}: APPROVED - {risk_check['reason']}")
                    # Check if position size was adjusted
                    if 'adjusted_size' in risk_check:
                        if trade_type == 'OPTION':
                            decision['contracts'] = int(risk_check['adjusted_size'])
                            # Option entry_price is option premium; multiply by 100 contracts multiplier.
                            decision['position_size'] = decision['contracts'] * decision['entry_price'] * 100
                        else:
                            decision['shares'] = int(risk_check['adjusted_size'])
                            decision['position_size'] = decision['shares'] * decision['entry_price']
                        decision['risk_adjusted'] = True
                        logger.info(
                            f"{ticker}: Position size adjusted (trade_type={trade_type})"
                        )
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
                        # Keep legacy `shares` key for performance logging; for options this is contract count.
                        'shares': decision.get('shares', decision.get('contracts', 0)),
                        'position_size': decision['position_size'],
                        'confidence': decision['confidence'],
                        # Some agents use `reason`, some use `reasoning`.
                        'reasoning': decision.get('reasoning') or decision.get('reason'),
                        'metrics': {
                            'rsi': decision.get('rsi'),
                            'drop_pct': decision.get('drop_pct'),
                            'volume_ratio': decision.get('volume_ratio'),
                            'confidence': decision['confidence']
                        },
                        'grok_sentiment': decision.get('grok_sentiment'),
                        'vision_analysis': decision.get('vision_analysis'),
                        'fundamental_analysis': decision.get('fundamental_analysis'),
                        'timestamp': datetime.now().isoformat(),
                        'llm_decision_id': decision.get('llm_decision_id'),
                    })
                    decision['signal_id'] = signal_id
                    if decision.get('llm_decision_id'):
                        get_llm_decision_tracker().link_signal(str(decision['llm_decision_id']), signal_id)
                    
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
                        'original_decision': decision,
                        'reject_stage': 'risk_guardian'
                    })

        # Risk gate transparency (approved vs rejected, aggregated by reason).
        risk_rejected_trades = [
            d for d in rejected_trades
            if isinstance(d, dict) and d.get("reject_stage") == "risk_guardian"
        ]
        risk_reason_counter = Counter(
            d.get("reason") or "Unknown"
            for d in risk_rejected_trades
        )
        top_rejected_reasons = [
            {"reason": reason, "count": count}
            for reason, count in risk_reason_counter.most_common(6)
        ]
        risk_gate_summary = {
            "approved_count": len(approved_trades),
            "rejected_count": len(risk_rejected_trades),
            "top_rejected_reasons": top_rejected_reasons
        }

        # Step 5: Execute approved trades (autonomous) or queue for human review
        from utils.pending_execution_queue import append_pending_batch

        mode = get_execution_mode()
        if mode == "human_in_loop" and approved_trades:
            logger.info("Step 5: Human-in-the-loop — deferring broker submission; writing pending queue…")
            append_pending_batch(
                source="daily_screening",
                run_id=run_id,
                candidates=candidates,
                trades=approved_trades,
                data_dir=DATA_DIR,
            )
            append_trust_event(
                "execution_deferred_hitl",
                {
                    "run_id": run_id,
                    "pending_count": len(approved_trades),
                    "policy_profile": policy.get("active_profile"),
                },
            )
            executed_trades = []
            execution_failures = []
            execution_gate_summary = {
                "executed_count": 0,
                "failed_count": 0,
                "pending_human_review": len(approved_trades),
                "execution_mode": mode,
                "top_failure_reasons": [],
            }
            logger.info(
                "Human-in-the-loop: %d approved trade(s) queued to data/pending_execution_queue.json — "
                "after review run: python orchestrator.py execute_pending",
                len(approved_trades),
            )
        else:
            logger.info("Step 5: Executing approved trades…")
            execution_results = await asyncio.gather(
                *[submit_approved_screening_trade(t, candidates, current_params) for t in approved_trades]
            )

            executed_trades = [trade for status, trade in execution_results if status == "success"]
            execution_failures = [trade for status, trade in execution_results if status == "failure"]

            # Execution transparency (approved trades that actually executed/fail).
            failure_reason_counter = Counter(
                (t.get("execution_error") or t.get("error") or "Unknown")
                for t in execution_failures
                if isinstance(t, dict)
            )
            top_failure_reasons = [
                {"reason": reason, "count": count}
                for reason, count in failure_reason_counter.most_common(6)
            ]
            execution_gate_summary = {
                "executed_count": len(executed_trades),
                "failed_count": len(execution_failures),
                "execution_mode": mode,
                "top_failure_reasons": top_failure_reasons,
            }
        
        # Step 6: Compile results
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        result = {
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'candidates_found': len(candidates),
            'candidates': candidates,
            'screening_meta': screening_meta,
            'entry_gate_summary': entry_gate_summary,
            'risk_gate_summary': risk_gate_summary,
            'execution_gate_summary': execution_gate_summary,
            'approved_trades': approved_trades,
            'executed_trades': executed_trades,
            'execution_failures': execution_failures,
            'rejected_trades': rejected_trades,
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
        append_trust_event("screening_completed", {
            "run_id": run_id,
            "policy_profile": policy.get("active_profile"),
            "candidates_found": len(candidates),
            "approved_count": len(approved_trades),
            "executed_count": len(executed_trades),
            "rejected_count": len(rejected_trades),
            "strict_mode": strict_mode,
            "hedge_gate_passed": hedge_gate_summary.get("passed"),
            "duration_seconds": duration,
        })
        log_screening_completed(
            run_id,
            {
                "policy_profile": policy.get("active_profile"),
                "candidates_found": len(candidates),
                "approved_count": len(approved_trades),
                "executed_count": len(executed_trades),
                "rejected_count": len(rejected_trades),
                "strict_mode": strict_mode,
                "hedge_gate_passed": hedge_gate_summary.get("passed"),
                "duration_seconds": duration,
            },
        )
        
        return result
        
    except Exception as e:
        # Ensure operators always see the underlying exception location.
        # Some environments may not route logger output to disk reliably,
        # so also print the full traceback to stdout.
        import traceback as _traceback
        err = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Error in daily screening workflow: {err}")
        tb_txt = _traceback.format_exc()
        logger.error("Traceback:\n%s", tb_txt)
        print(tb_txt)
        
        # Return error result
        result = {
            'timestamp': datetime.now().isoformat(),
            'error': str(e),
            'error_type': type(e).__name__,
            'error_trace': tb_txt[-4000:],
            'candidates_found': 0,
            'approved_trades': [],
            'rejected_trades': [],
            'screening_meta': {},
            'entry_gate_summary': {},
            'risk_gate_summary': {},
            'execution_gate_summary': {},
            'risk_status': get_risk_status()
        }
        save_daily_signals(result)
        append_trust_event("screening_failed", {
            "run_id": run_id,
            "policy_profile": policy.get("active_profile"),
            "error_type": type(e).__name__,
            "error": str(e),
        })
        log_screening_failed(run_id, type(e).__name__, str(e))
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


def _parse_position_entry_dt(pos: dict) -> datetime | None:
    raw = pos.get("entry_date") or pos.get("entry_time")
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    try:
        s = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def _record_closed_trade_and_llm_learning(signal: dict, pos: dict | None) -> None:
    """Full exit: update decisions_log outcome + LLM decision tracker + optional lesson (async thread)."""
    try:
        if str(signal.get("action") or "") != "SELL_ALL":
            return
        if not pos:
            return
        signal_id = pos.get("signal_id")
        if not signal_id:
            return
        filled_price = signal.get("filled_price")
        sell_qty = signal.get("sell_qty")
        if filled_price is None or sell_qty is None or float(sell_qty) <= 0:
            return
        filled_price = float(filled_price)
        sell_qty = float(sell_qty)
        trade_type = (pos or {}).get("type", "STOCK")
        if trade_type == "OPTION":
            entry_price = float((pos or {}).get("entry_premium") or 0)
            pnl_dollars = (filled_price - entry_price) * sell_qty * 100.0
        else:
            entry_price = float((pos or {}).get("entry_price") or 0)
            pnl_dollars = (filled_price - entry_price) * sell_qty

        frac_pnl = float(signal.get("pnl_pct") or 0.0)
        pnl_pct_pts = frac_pnl * 100.0

        et = _parse_position_entry_dt(pos)
        hold_days = 0
        if et:
            hold_days = max(0, (datetime.now() - et).days)

        outcome_data = {
            "exit_price": filled_price,
            "pnl_pct": pnl_pct_pts,
            "pnl_dollars": pnl_dollars,
            "hold_days": hold_days,
            "exit_reason": str(signal.get("reason") or "exit"),
            "exit_timestamp": datetime.now().isoformat(),
        }
        track_outcome(str(signal_id), outcome_data)

        duration_hours = None
        if et:
            duration_hours = (datetime.now() - et).total_seconds() / 3600.0

        llm_outcome = {
            "pnl": pnl_dollars,
            "pnl_pct": pnl_pct_pts,
            "duration_hours": duration_hours,
            "exit_reason": outcome_data["exit_reason"],
            "exit_price": filled_price,
        }
        tracker = get_llm_decision_tracker()
        if tracker.record_outcome(str(signal_id), llm_outcome):

            def _learn() -> None:
                try:
                    rec = tracker.get_decision_by_signal(str(signal_id))
                    if rec:
                        LLMLearningAgent().learn_from_trade(rec)
                except Exception as exc:
                    logger.warning("LLM learning post-exit failed: %s", exc)

            if str(os.getenv("FORTRESS_LLM_LEARNING_ON_EXIT", "1")).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }:
                threading.Thread(target=_learn, daemon=True).start()
    except Exception as e:
        logger.warning("Closed-trade recording failed: %s: %s", type(e).__name__, e)


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
        positions_by_ticker = {p.get('ticker'): p for p in positions}
        
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
            action = signal.get('action')
            if not isinstance(action, str) or not action.startswith('SELL'):
                return None
            
            ticker = signal['ticker']
            sell_qty = signal.get('sell_qty', 0)
            
            if sell_qty <= 0:
                return None
            
            # Execute sell order
            order_result = await asyncio.to_thread(execute_sell_order, ticker, sell_qty)
            order_result = await asyncio.to_thread(_refresh_order_result, order_result)
            
            if order_result['success'] and _order_is_filled(order_result):
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
                    await asyncio.to_thread(
                        update_position_quantity,
                        ticker,
                        sell_qty,
                        signal.get('tier')
                    )
                
                return ('success', signal)
            else:
                status = order_result.get("status")
                detail = order_result.get("error") or f"not filled yet (status={status})"
                logger.warning(f"{ticker}: Exit order not finalized - {detail}")
                signal['order_id'] = order_result.get('order_id')
                signal['order_status'] = status
                signal['filled_qty'] = order_result.get('filled_qty')
                signal['filled_price'] = order_result.get('filled_price')
                signal['executed'] = False
                signal['execution_error'] = detail
                return ('failure', signal)
        
        # Execute all exits in parallel
        exit_results = await asyncio.gather(*[execute_exit(s) for s in exit_signals])
        
        executed_exits = [signal for result in exit_results if result and result[0] == 'success' for _, signal in [result]]
        exit_failures = [signal for result in exit_results if result and result[0] == 'failure' for _, signal in [result]]

        # Update risk guardian state and write realized P&L ledger for next screening run.
        ledger_order_ids = _read_pnl_ledger_order_ids()
        for signal in executed_exits:
            try:
                pos = positions_by_ticker.get(signal.get('ticker'))
                filled_price = signal.get('filled_price')
                sell_qty = signal.get('sell_qty', 0)

                if filled_price is None or sell_qty is None or float(sell_qty) <= 0:
                    continue

                filled_price = float(filled_price)
                sell_qty = float(sell_qty)

                trade_type = (pos or {}).get('type', 'STOCK')
                if trade_type == 'OPTION':
                    entry_price = float((pos or {}).get('entry_premium', 0) or 0)
                    # Option premium is per share; contract multiplier is 100.
                    pnl_dollars = (filled_price - entry_price) * sell_qty * 100
                else:
                    # If position already rotated out of the local file, infer entry from pnl_pct.
                    if pos:
                        entry_price = float(pos.get('entry_price', 0) or 0)
                    else:
                        derived = _derive_entry_price_from_signal(signal, filled_price)
                        if derived is None:
                            continue
                        entry_price = derived
                    pnl_dollars = (filled_price - entry_price) * sell_qty

                update_consecutive_losses({'pnl': pnl_dollars})

                _append_pnl_ledger_once({
                    'timestamp': datetime.now().isoformat(),
                    'order_id': signal.get('order_id'),
                    'ticker': signal.get('ticker'),
                    'underlying_ticker': (pos or {}).get('underlying_ticker'),
                    'type': trade_type,
                    'pnl': pnl_dollars,
                    'pnl_pct': signal.get('pnl_pct')
                }, ledger_order_ids)

                _record_closed_trade_and_llm_learning(signal, pos)
            except Exception as e:
                logger.warning(f"Failed to record P&L ledger entry: {type(e).__name__}: {str(e)}")

        # Reconcile delayed fills from earlier monitor runs that were not filled at submit-time.
        # This closes the accounting gap where exit order eventually fills but pnl_ledger stays empty.
        try:
            date_str = datetime.now().strftime('%Y%m%d')
            exit_file = DATA_DIR / f"exit_signals_{date_str}.json"
            signal_by_order_id = {}
            if exit_file.exists() and alpaca_client is not None:
                runs_blob = json.loads(exit_file.read_text())
                runs = runs_blob.get('runs', [])
                for run in runs:  # scan full day history for delayed fills
                    for signal in run.get('exit_signals', []):
                        order_id = signal.get('order_id')
                        action = signal.get('action')
                        if not order_id or not isinstance(action, str) or not action.startswith("SELL"):
                            continue
                        if str(order_id) in ledger_order_ids:
                            continue
                        signal_by_order_id[str(order_id)] = signal
                        try:
                            order = alpaca_client.get_order_by_id(str(order_id))
                            status = str(getattr(order, "status", "")).strip().lower()
                            if not (status == "filled" or status.endswith(".filled")):
                                continue
                            filled_price = getattr(order, "filled_avg_price", None)
                            filled_qty = getattr(order, "filled_qty", None)
                            if filled_price is None or filled_qty is None:
                                continue
                            filled_price = float(filled_price)
                            sell_qty = float(signal.get('sell_qty') or filled_qty or 0)
                            if sell_qty <= 0:
                                continue

                            pos = positions_by_ticker.get(signal.get('ticker'))
                            trade_type = (pos or {}).get('type', 'STOCK')
                            if trade_type == 'OPTION':
                                entry_price = float((pos or {}).get('entry_premium', 0) or 0)
                                pnl_dollars = (filled_price - entry_price) * sell_qty * 100
                            else:
                                if pos:
                                    entry_price = float(pos.get('entry_price', 0) or 0)
                                else:
                                    derived = _derive_entry_price_from_signal(signal, filled_price)
                                    if derived is None:
                                        continue
                                    entry_price = derived
                                pnl_dollars = (filled_price - entry_price) * sell_qty

                            if _append_pnl_ledger_once({
                                'timestamp': datetime.now().isoformat(),
                                'order_id': str(order_id),
                                'ticker': signal.get('ticker'),
                                'underlying_ticker': (pos or {}).get('underlying_ticker'),
                                'type': trade_type,
                                'pnl': pnl_dollars,
                                'pnl_pct': signal.get('pnl_pct')
                            }, ledger_order_ids):
                                update_consecutive_losses({'pnl': pnl_dollars})
                        except Exception:
                            continue

                # Second reconciliation source: Alpaca filled SELL order history.
                # Captures fills that happened outside exit_signals (manual/API sell path).
                try:
                    after_ts = datetime.now(pytz.UTC) - timedelta(days=2)
                    req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after_ts, nested=False)
                    try:
                        recent_orders = alpaca_client.get_orders(filter=req)
                    except TypeError:
                        recent_orders = alpaca_client.get_orders(req)
                    except Exception:
                        recent_orders = []

                    for order in recent_orders or []:
                        try:
                            order_id = str(getattr(order, "id", "") or "")
                            if not order_id or order_id in ledger_order_ids:
                                continue
                            status = str(getattr(order, "status", "")).strip().lower()
                            if not (status == "filled" or status.endswith(".filled")):
                                continue
                            side = str(getattr(order, "side", "")).strip().lower()
                            if not (side == "sell" or side.endswith(".sell")):
                                continue

                            ticker = str(getattr(order, "symbol", "") or "").strip().upper()
                            if not ticker:
                                continue
                            filled_price = getattr(order, "filled_avg_price", None)
                            filled_qty = getattr(order, "filled_qty", None)
                            if filled_price is None or filled_qty is None:
                                continue
                            filled_price = float(filled_price)
                            sell_qty = float(filled_qty)
                            if sell_qty <= 0:
                                continue

                            pos = positions_by_ticker.get(ticker)
                            trade_type = (pos or {}).get('type', 'STOCK')
                            signal = signal_by_order_id.get(order_id) or {}
                            if trade_type == 'OPTION':
                                entry_price = float((pos or {}).get('entry_premium', 0) or 0)
                                if entry_price <= 0:
                                    continue
                                pnl_dollars = (filled_price - entry_price) * sell_qty * 100
                            else:
                                if pos:
                                    entry_price = float(pos.get('entry_price', 0) or 0)
                                else:
                                    # If position is fully closed, infer from available pnl_pct.
                                    derived = _derive_entry_price_from_signal(signal, filled_price)
                                    if derived is None:
                                        continue
                                    entry_price = derived
                                pnl_dollars = (filled_price - entry_price) * sell_qty

                            if _append_pnl_ledger_once({
                                'timestamp': datetime.now().isoformat(),
                                'order_id': order_id,
                                'ticker': ticker,
                                'underlying_ticker': (pos or {}).get('underlying_ticker'),
                                'type': trade_type,
                                'pnl': pnl_dollars,
                                'pnl_pct': signal.get('pnl_pct')
                            }, ledger_order_ids):
                                update_consecutive_losses({'pnl': pnl_dollars})
                        except Exception:
                            continue
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"PnL reconciliation skipped: {type(e).__name__}: {str(e)}")
        
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


def update_position_quantity(ticker, qty_sold, tier=None):
    """
    Update position quantity after partial sale.
    
    Args:
        ticker: Stock ticker
        qty_sold: Number of shares sold
        tier: Optional tier name (e.g. 'tier1', 'tier2', 'tier3') to mark as sold
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

                # Mark tier as sold so we don't repeatedly sell the same tranche.
                if tier and 'tiers_sold' in pos and isinstance(pos['tiers_sold'], dict):
                    pos['tiers_sold'][tier] = True
                
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
    # Risk guardian expects each position to have:
    # - `value` (notional/exposure used for risk checks)
    # - `sector` (for concentration checks)
    #
    # Stored positions historically omitted `value`, so compute it here.
    enhanced_positions = []
    for pos in positions:
        pos = dict(pos)
        trade_type = pos.get('type', 'STOCK')
        sector = pos.get('sector', 'Unknown')

        if trade_type == 'OPTION':
            qty = float(pos.get('qty', 0) or 0)
            entry_premium = float(pos.get('entry_premium', 0) or 0)
            computed_value = qty * entry_premium * 100.0
        else:
            shares = float(pos.get('shares', pos.get('qty', 0)) or 0)
            entry_price = float(pos.get('entry_price', 0) or 0)
            computed_value = shares * entry_price

        if pos.get('value') is None:
            pos['value'] = computed_value
        else:
            try:
                pos['value'] = float(pos.get('value'))
            except Exception:
                pos['value'] = computed_value

        pos['sector'] = sector
        enhanced_positions.append(pos)

    positions = enhanced_positions

    # Realized P&L is tracked in pnl_ledger.jsonl (written on exit executions).
    today_pnl = 0.0
    week_pnl = 0.0
    now = datetime.now()

    if PNL_LEDGER_FILE.exists():
        try:
            with open(PNL_LEDGER_FILE, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    ts = datetime.fromisoformat(rec["timestamp"])
                    pnl = float(rec.get("pnl", 0))

                    if ts.date() == now.date():
                        today_pnl += pnl
                    if ts >= (now - timedelta(days=7)):
                        week_pnl += pnl
        except Exception as e:
            logger.warning(f"Failed reading PnL ledger: {type(e).__name__}: {str(e)}")

    return {
        'equity': portfolio_value,
        'positions': positions,
        'today_pnl': today_pnl,
        'week_pnl': week_pnl
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


def flush_pending_execution_queue() -> dict:
    """
    Submit all trades queued in ``data/pending_execution_queue.json`` (human-in-the-loop).

    Clears the queue after processing (check logs / trust ledger for failures).
    """
    from utils.pending_execution_queue import clear_batches, load_batches

    batches = load_batches(DATA_DIR)
    if not batches:
        logger.info("execute_pending: no pending batches in data/pending_execution_queue.json")
        return {"ok": True, "message": "no pending batches", "batches": 0, "executed": 0, "failed": 0}

    # If markets are closed, do not clear anything.
    # This makes it safe for cron/systemd to call `execute_pending` repeatedly.
    try:
        from utils.market_calendar import is_us_equity_rth_open

        if not is_us_equity_rth_open():
            logger.info(
                "execute_pending: RTH closed; deferring %d pending batch(es) without clearing queue",
                len(batches),
            )
            return {
                "ok": True,
                "message": "market closed; pending kept",
                "batches": len(batches),
                "executed": 0,
                "failed": 0,
                "deferred": True,
            }
    except Exception:
        # Never let this guard break execution; if it's broken, fallback to old behavior.
        pass

    current_params = load_current_params()

    async def _run_all():
        out = []
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            candidates = batch.get("candidates") or []
            trades = batch.get("trades") or []
            for trade in trades:
                if isinstance(trade, dict):
                    out.append(await submit_approved_screening_trade(trade, candidates, current_params))
        return out

    results = asyncio.run(_run_all())
    succeeded = sum(1 for st, _ in results if st == "success")
    failed = sum(1 for st, _ in results if st == "failure")
    clear_batches(DATA_DIR)
    append_trust_event(
        "pending_execution_flushed",
        {
            "batches": len(batches),
            "executed": succeeded,
            "failed": failed,
        },
    )
    logger.info(
        "execute_pending: batches=%d trade_results success=%d fail=%d (queue cleared)",
        len(batches),
        succeeded,
        failed,
    )
    return {"ok": True, "batches": len(batches), "executed": succeeded, "failed": failed}


def _orchestrator_repo_root() -> Path:
    return _ORCHESTRATOR_ROOT


def ensure_repo_root_cwd() -> Path:
    """
    Align process cwd with repo (paths for data/logs are absolute; cwd still matters for subprocesses).
    """
    root = _ORCHESTRATOR_ROOT
    os.chdir(root)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    return root


def print_regime_health_banner() -> None:
    """Stdout snapshot: latest fortress report + hedging_recommendations.json (read-only)."""
    root = _orchestrator_repo_root()
    data = root / "data"
    print("\n" + "=" * 72)
    print("REGIME / HEDGE SNAPSHOT (read-only)")
    print("=" * 72)
    report, meta = _load_latest_fortress_report(max_age_hours=None)
    if report:
        mc = report.get("market_conditions") or {}
        print(
            f"  fortress_report: regime={mc.get('regime')}  vix={mc.get('vix')}  "
            f"age_h={meta.get('age_hours')}  path={meta.get('path')}"
        )
    else:
        print("  fortress_report: (none — run: python3 orchestrator.py fortress)")
    hp = data / "hedging_recommendations.json"
    if hp.exists():
        try:
            h = json.loads(hp.read_text(encoding="utf-8"))
            note = h.get("note") or h.get("summary") or "loaded"
            if not isinstance(note, str):
                note = json.dumps(note)[:120]
            print(f"  hedging_recommendations.json: ok — {str(note)[:120]}")
        except Exception as e:
            print(f"  hedging_recommendations.json: read error ({type(e).__name__})")
    else:
        print("  hedging_recommendations.json: (missing — refresh fortress / hedge cycle)")
    print("=" * 72 + "\n")


def print_latest_entry_skips() -> None:
    """Print entry_gate_summary from newest data/daily_signals_*.json (by mtime)."""
    root = _orchestrator_repo_root()
    pattern = str(root / "data" / "daily_signals_*.json")
    paths = [Path(p) for p in glob.glob(pattern)]
    if not paths:
        print("No data/daily_signals_*.json files found.")
        return
    path = max(paths, key=lambda p: p.stat().st_mtime)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to read {path}: {e}")
        return
    eg = doc.get("entry_gate_summary")
    print(f"\nLatest (by mtime): {path.name}")
    if not isinstance(eg, dict) or not eg:
        keys = sorted(doc.keys()) if isinstance(doc, dict) else []
        err = doc.get("error") if isinstance(doc, dict) else None
        cf = doc.get("candidates_found") if isinstance(doc, dict) else None
        print(
            "entry_gate_summary: (missing or empty — screen may have failed before entry evaluation, "
            "or this file is a stub.)"
        )
        if err:
            print(f"  error: {err}")
        if cf is not None:
            print(f"  candidates_found: {cf}")
        if keys:
            print(f"  top-level keys: {', '.join(keys)}")
        print(f"  Inspect full file: {path}")
        return
    print(json.dumps(eg, indent=2))
    tops = eg.get("top_skip_reasons") or []
    legacy = tops and all(
        isinstance(r, dict) and str(r.get("reason") or "").strip() == "No suitable option found" for r in tops
    )
    if legacy and len(tops) == 1:
        print(
            "\nNote: This reason was often written by older entry_agent code over real SKIP causes "
            "(RSI / window / stabilization). Deploy latest `agents/entry_agent.py` and run "
            "`python3 orchestrator.py screen` once — then print_entry_skips will show true reasons."
        )
    if tops:
        print("\nTop skip reasons (fix one lever at a time; see .env.example ENTRY_* / agents/entry_agent.py):")
        for row in tops[:6]:
            if isinstance(row, dict):
                print(f"  - {row.get('count')}×  {row.get('reason')}")


def run_multi_timeframe_framework(portfolio_value: float) -> dict:
    """
    Task-1 multi-timeframe sleeve planner.
    Produces a deterministic sleeve allocation plan from current screener candidates.
    """
    cfg = load_strategy_allocation_config()
    candidates = run_screener()
    report, _meta = _load_latest_fortress_report(max_age_hours=FORTRESS_REPORT_MAX_AGE_HOURS)
    regime = "MIXED"
    vix = None
    if isinstance(report, dict):
        mc = report.get("market_conditions") or {}
        regime = str(mc.get("regime") or regime)
        try:
            vix = float(mc.get("vix")) if mc.get("vix") is not None else None
        except (TypeError, ValueError):
            vix = None

    managers = {
        "day_trading": DayTradingManager(),
        "swing_trading": SwingTradingManager(),
        "position_trading": PositionTradingManager(),
    }
    sleeves_out = {}
    for key, mgr in managers.items():
        s = cfg.sleeves.get(key)
        if s is None:
            continue
        active = bool(s.enabled)
        if active and s.activation.allowed_regimes:
            active = regime in set(s.activation.allowed_regimes)
        if active and s.activation.min_vix is not None and vix is not None:
            active = vix >= float(s.activation.min_vix)
        if active and s.activation.max_vix is not None and vix is not None:
            active = vix <= float(s.activation.max_vix)
        result = mgr.evaluate(
            candidates,
            sleeve_cfg=s.model_dump(),
            regime=regime,
            vix=vix,
            portfolio_value=portfolio_value,
        )
        result["active"] = bool(active)
        sleeves_out[key] = result
        mgr.record_outcome(result, data_dir=DATA_DIR)

    out = {
        "timestamp": datetime.now().isoformat(),
        "portfolio_value": portfolio_value,
        "regime": regime,
        "vix": vix,
        "candidates_found": len(candidates),
        "sleeves": sleeves_out,
    }
    fn = DATA_DIR / f"multi_timeframe_plan_{datetime.now().strftime('%Y%m%d')}.json"
    fn.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def run_ops_recovery(raw_argv: list[str]) -> int:
    """
    Operator one-shot: cd repo root → optional fortress → screen → execute_pending.
    Flags: --no-fortress  --no-screen  --no-pending
    Optional trailing arg: portfolio_value for screen.
    """
    ensure_repo_root_cwd()
    try:
        (_orchestrator_repo_root() / "logs" / ".ops_recovery_last_run").write_text(
            datetime.now(timezone.utc).isoformat() + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    args = [a for a in raw_argv if a]
    no_fortress = "--no-fortress" in args
    no_screen = "--no-screen" in args
    no_pending = "--no-pending" in args
    rest = [a for a in args if not str(a).startswith("--")]
    portfolio_value = float(rest[0]) if rest else get_default_portfolio_usd()

    print_regime_health_banner()

    if not no_fortress:
        if not is_agent_enabled("fortress"):
            print("[ops_recovery] fortress disabled in fortress_runtime.yaml — skip.")
        else:
            print("[ops_recovery] Running fortress…")
            run_fortress()
    if not no_screen:
        if not is_agent_enabled("daily_screen"):
            print("[ops_recovery] daily_screen disabled — skip.")
        else:
            print(f"[ops_recovery] Running screen (portfolio ${portfolio_value:,.2f})…")
            run_daily_screening(portfolio_value)
    if not no_pending:
        print("[ops_recovery] Flushing pending queue (no-op if empty)…")
        out = flush_pending_execution_queue()
        print(json.dumps(out, indent=2))

    print("\n[ops_recovery] Done. Tail logs/orchestrator.log and logs/sniper.log for freshness.\n")
    return 0


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
        print("  python orchestrator.py spy_swing [--execute] [portfolio_value] - SPY swing agent (default shadow; equity from runtime config)")
        print("  python orchestrator.py execute_pending            - Submit queued HITL trades (see FORTRESS_EXECUTION_MODE)")
        print("  python orchestrator.py headline_event [--fixture] - Headline event agent (shadow; --fixture = sample fixture)")
        print("  python orchestrator.py multi_timeframe [portfolio_value] - Run task-1 sleeve allocation planner")
        print("  python orchestrator.py sector_rotation [portfolio_value] - Build monthly sector rotation signal")
        print("  python orchestrator.py geographic_allocation [portfolio_value] - Build international allocation plan")
        print("  python orchestrator.py execute_sector_rotation [--force] - Execute sector rotation sleeve")
        print("  python orchestrator.py execute_geographic_allocation [--force] - Execute geographic allocation sleeve")
        print("  python orchestrator.py cio_cycle - Produce top-level CIO directive")
        print("  python orchestrator.py scout_swarm - Run scout swarm queue builder")
        print("  python orchestrator.py analyst_ensemble - Score opportunities with analyst quorum")
        print("  python orchestrator.py generate_intelligence_brief - Generate daily self-QA intelligence brief")
        print("  python orchestrator.py evolve - Run recursive self-improvement cycle")
        print("  python orchestrator.py verify_learning            - LLM provider + recursive-learning file status")
        print("  python orchestrator.py ops_recovery [--no-fortress] [--no-screen] [--no-pending] [portfolio_value]")
        print("  python orchestrator.py regime_check               - Print fortress + hedging file snapshot")
        print("  python orchestrator.py print_entry_skips          - Print latest daily_signals entry_gate_summary")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command in ("ops_recovery", "ops-recovery"):
        sys.exit(run_ops_recovery(sys.argv[2:]))
    
    if command in ("regime_check", "regime-check"):
        ensure_repo_root_cwd()
        print_regime_health_banner()
        sys.exit(0)
    
    if command in ("print_entry_skips", "print-entry-skips"):
        ensure_repo_root_cwd()
        print_latest_entry_skips()
        sys.exit(0)

    if command in ("multi_timeframe", "multi-timeframe"):
        ensure_repo_root_cwd()
        portfolio_value = float(sys.argv[2]) if len(sys.argv) > 2 else get_default_portfolio_usd()
        out = run_multi_timeframe_framework(portfolio_value)
        print(json.dumps(out, indent=2, default=str))
        sys.exit(0)

    if command in ("sector_rotation", "sector-rotation"):
        ensure_repo_root_cwd()
        portfolio_value = float(sys.argv[2]) if len(sys.argv) > 2 else get_default_portfolio_usd()
        report, _meta = _load_latest_fortress_report(max_age_hours=FORTRESS_REPORT_MAX_AGE_HOURS)
        vix = None
        if isinstance(report, dict):
            mc = report.get("market_conditions") or {}
            try:
                vix = float(mc.get("vix")) if mc.get("vix") is not None else None
            except (TypeError, ValueError):
                vix = None
        out = run_sector_rotation_manager(data_dir=DATA_DIR, portfolio_value=portfolio_value, vix=vix)
        print(json.dumps(out, indent=2, default=str))
        sys.exit(0)

    if command in ("geographic_allocation", "geographic-allocation"):
        ensure_repo_root_cwd()
        portfolio_value = float(sys.argv[2]) if len(sys.argv) > 2 else get_default_portfolio_usd()
        report, _meta = _load_latest_fortress_report(max_age_hours=FORTRESS_REPORT_MAX_AGE_HOURS)
        vix = None
        regime = "UNKNOWN"
        if isinstance(report, dict):
            regime = str(report.get("market_regime") or "UNKNOWN")
            mc = report.get("market_conditions") or {}
            try:
                vix = float(mc.get("vix")) if mc.get("vix") is not None else None
            except (TypeError, ValueError):
                vix = None
        out = run_geographic_allocation_manager(
            portfolio_value=portfolio_value,
            data_dir=DATA_DIR,
            regime=regime,
            vix=vix,
        )
        print(json.dumps(out, indent=2, default=str))
        sys.exit(0)

    if command in ("execute_sector_rotation", "execute-sector-rotation"):
        ensure_repo_root_cwd()
        force = "--force" in sys.argv[2:]
        out = run_sector_rotation_execution(force=force)
        print(json.dumps(out, indent=2, default=str))
        sys.exit(0)

    if command in ("execute_geographic_allocation", "execute-geographic-allocation"):
        ensure_repo_root_cwd()
        force = "--force" in sys.argv[2:]
        out = run_geographic_allocation_execution(force=force)
        print(json.dumps(out, indent=2, default=str))
        sys.exit(0)

    if command in ("cio_cycle", "cio-cycle"):
        ensure_repo_root_cwd()
        out = run_cio_cycle(data_dir=DATA_DIR)
        print(json.dumps(out, indent=2, default=str))
        sys.exit(0)

    if command in ("scout_swarm", "scout-swarm"):
        ensure_repo_root_cwd()
        out = run_scout_swarm(data_dir=DATA_DIR)
        print(json.dumps(out, indent=2, default=str))
        sys.exit(0)

    if command in ("analyst_ensemble", "analyst-ensemble"):
        ensure_repo_root_cwd()
        queue = _read_latest_json(DATA_DIR, "scout_opportunity_queue_*.json")
        opportunities = []
        if isinstance(queue, dict):
            opportunities = queue.get("opportunities") or []
        out = run_analyst_ensemble(opportunities=opportunities, data_dir=DATA_DIR)
        print(json.dumps(out, indent=2, default=str))
        sys.exit(0)

    if command in ("generate_intelligence_brief", "generate-intelligence-brief"):
        ensure_repo_root_cwd()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        brief = generate_brief(data_dir=DATA_DIR, logs_dir=Path("logs"))
        day = datetime.now().strftime("%Y%m%d")
        json_path = DATA_DIR / f"fortress_intelligence_brief_{day}.json"
        md_path = DATA_DIR / f"fortress_intelligence_brief_{day}.md"
        json_path.write_text(json.dumps(brief, indent=2, default=str), encoding="utf-8")
        md_path.write_text(generate_markdown_summary(brief), encoding="utf-8")
        print(json.dumps({"ok": True, "json_path": str(json_path), "markdown_path": str(md_path)}, indent=2))
        sys.exit(0)

    if command in ("evolve", "recursive_evolve", "recursive-evolve"):
        ensure_repo_root_cwd()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        out = run_recursive_evolution(data_dir=DATA_DIR)
        print(json.dumps(out, indent=2, default=str))
        sys.exit(0)

    if command in ("verify_learning", "verify-learning"):
        ensure_repo_root_cwd()
        print(json.dumps(verify_learning(), indent=2, default=str))
        sys.exit(0)

    # Cron/systemd often starts with wrong cwd; keep data/ + logs/ under repo root.
    ensure_repo_root_cwd()
    
    if command == "screen":
        if not is_agent_enabled("daily_screen"):
            print("Fortress runtime: daily_screen disabled (config/fortress_runtime.yaml).")
            sys.exit(0)
        portfolio_value = float(sys.argv[2]) if len(sys.argv) > 2 else get_default_portfolio_usd()
        print(f"\nRunning daily screening workflow (Portfolio: ${portfolio_value:,.2f})...")
        print("Using async parallel execution for 5x faster analysis...")
        result = run_daily_screening(portfolio_value)
        
        print("\n" + "=" * 80)
        print("SCREENING RESULTS")
        print("=" * 80)
        print(f"Candidates found: {result['candidates_found']}")
        print(f"Approved trades: {len(result['approved_trades'])}")
        print(f"Rejected trades: {len(result['rejected_trades'])}")

        n_app = len(result.get("approved_trades") or [])
        n_rej = len(result.get("rejected_trades") or [])
        cf = int(result.get("candidates_found") or 0)
        if cf > 0 and n_app == 0 and n_rej == 0:
            eg0 = result.get("entry_gate_summary") or {}
            print(
                f"\nEntry gate: BUY {eg0.get('buy_count', 0)} / SKIP {eg0.get('skip_count', 0)} "
                "(no BUYs reached risk approval — normal when all names fail entry timing/RSI/etc.)."
            )
            for row in (eg0.get("top_skip_reasons") or [])[:5]:
                if isinstance(row, dict):
                    print(f"  Skip: {row.get('count')}×  {row.get('reason')}")
            print("  Detail: python3 orchestrator.py print_entry_skips")
        
        eg = result.get("execution_gate_summary") or {}
        if eg.get("pending_human_review"):
            print(f"\nHuman-in-the-loop: {eg['pending_human_review']} approved trade(s) queued — run: python orchestrator.py execute_pending")

        if result.get('executed_trades'):
            print("\nExecuted Trades:")
            for trade in result['executed_trades']:
                print(f"  {trade['ticker']}: {trade['shares']} shares @ ${trade['entry_price']:.2f} = ${trade['position_size']:.2f}")
                print(f"    Order ID: {trade['order_id']}")
                print(f"    Status: {trade['order_status']}")
                conf = trade.get("confidence")
                if conf is not None:
                    print(f"    Confidence: {conf:.2f}")
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
        if not is_agent_enabled("position_monitor"):
            print("Fortress runtime: position_monitor disabled (config/fortress_runtime.yaml).")
            sys.exit(0)
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
        if not is_agent_enabled("meta_architect"):
            print("Fortress runtime: meta_architect disabled (config/fortress_runtime.yaml).")
            sys.exit(0)
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
        if not is_agent_enabled("fortress"):
            print("Fortress runtime: fortress disabled (config/fortress_runtime.yaml).")
            sys.exit(0)
        print("\nRunning complete fortress hedging system...")
        result = run_fortress()
        
        print("\n" + "=" * 80)
        print("FORTRESS HEDGING SYSTEM RESULTS")
        print("=" * 80)
        if result:
            mc = result.get("market_conditions") or {}
            print(f"Market regime: {mc.get('regime', 'N/A')}")
            strat = result.get("strategies") or result.get("recommendations") or {}
            print(f"Strategies evaluated: {len(strat)}")
            for strategy, data in strat.items():
                if data:
                    print(f"{strategy}: {data}")
        else:
            print("No results returned from fortress hedging system.")

    elif command == "execute_pending":
        print("\nFlushing human-in-the-loop pending queue (data/pending_execution_queue.json)…")
        out = flush_pending_execution_queue()
        print(json.dumps(out, indent=2))

    elif command == "snipe":
        if not is_agent_enabled("intraday_sniper"):
            print("Fortress runtime: intraday_sniper disabled (config/fortress_runtime.yaml).")
            sys.exit(0)
        portfolio_value = float(sys.argv[2]) if len(sys.argv) > 2 else get_default_portfolio_usd()
        logger.info(f"Running intraday sniper (Portfolio: ${portfolio_value:,.2f})...")
        opportunities = scan_intraday_opportunities(portfolio_value)
        
        logger.info("=" * 80)
        logger.info("INTRADAY SNIPER RESULTS")
        logger.info("=" * 80)
        logger.info(f"Opportunities found: {len(opportunities)}")
        
        if not opportunities:
            logger.info("No opportunities found")
            sys.exit(0)

        # Risk profile (match daily strict-mode behavior)
        risk_status = get_risk_status()
        consecutive_losses = int(risk_status.get("consecutive_losses") or 0)
        circuit_breaker_active = bool(risk_status.get("circuit_breaker_active"))
        strict_mode = circuit_breaker_active or consecutive_losses >= 2

        account_info = get_account_info()
        if not account_info:
            logger.error("Intraday sniper: could not load Alpaca account info; execution disabled.")
            sys.exit(0)

        current_positions = load_positions()
        portfolio_data = build_portfolio_data(current_positions, portfolio_value)
        existing_tickers = {str(p.get("ticker") or "").upper() for p in current_positions if p.get("ticker")}

        policy = get_profile_bundle()
        exec_cfg = policy.get("execution") or {}
        max_trades_per_run = int(exec_cfg.get("sniper_max_trades_per_run") or os.getenv("SNIPER_MAX_TRADES_PER_RUN", "3"))
        executed = 0
        approved = []
        rejected = []
        deferred_snipe_trades: list[dict] = []

        for opp in opportunities:
            if executed >= max_trades_per_run:
                break

            ticker = str(opp.get("ticker") or "").strip().upper()
            entry_price = float(opp.get("entry_price") or 0)
            metrics = opp.get("metrics") or {}

            if not ticker or entry_price <= 0:
                continue
            if ticker in existing_tickers:
                continue

            decision = evaluate_quick_entry(ticker, entry_price, metrics, portfolio_value=portfolio_value)
            if not isinstance(decision, dict) or decision.get("action") != "BUY":
                rejected.append({"ticker": ticker, "reason": (decision or {}).get("reason") or "not_buy"})
                continue

            shares = int(decision.get("shares") or 0)
            position_value = float(decision.get("position_value") or 0)
            if shares < 1 or position_value <= 0:
                rejected.append({"ticker": ticker, "reason": "invalid_position_size"})
                continue

            required_capital = position_value * BUYING_POWER_BUFFER
            if account_info.get("buying_power", 0) < required_capital:
                rejected.append({"ticker": ticker, "reason": "insufficient_buying_power"})
                continue

            new_position = {
                "ticker": ticker,
                "size": shares,
                "value": position_value,
                "sector": "Unknown",
            }
            risk_check = check_risk_limits(portfolio_data, new_position, strict_mode=strict_mode)
            if not risk_check.get("approved"):
                rejected.append({"ticker": ticker, "reason": risk_check.get("reason") or "risk_rejected"})
                continue

            if "adjusted_size" in risk_check:
                shares = int(risk_check["adjusted_size"])
                position_value = shares * entry_price
                decision["shares"] = shares
                decision["position_value"] = position_value

            order_result = execute_buy_order(ticker, shares, entry_price)
            if order_result.get("success") and _order_is_filled(order_result):
                order_id = order_result.get("order_id")
                add_position({
                    "ticker": ticker,
                    "shares": shares,
                    "entry_price": entry_price,
                    "entry_date": datetime.now().isoformat(),
                    "order_id": order_id,
                    "sector": "Unknown",
                    "stop_loss_pct": -0.02,
                    "take_profit_pct": 0.05,
                    "tiers_sold": {"tier1": False, "tier2": False, "tier3": False},
                })

                portfolio_data["positions"].append({"ticker": ticker, "value": position_value, "sector": "Unknown"})
                existing_tickers.add(ticker)
                executed += 1
                approved.append({"ticker": ticker, "shares": shares, "entry_price": entry_price, "order_id": order_id})

        if get_execution_mode() == "human_in_loop" and deferred_snipe_trades:
            from utils.pending_execution_queue import append_pending_batch

            snipe_rid = f"snipe_{int(pytime.time())}"
            append_pending_batch(
                source="intraday_sniper",
                run_id=snipe_rid,
                candidates=[],
                trades=deferred_snipe_trades,
                data_dir=DATA_DIR,
            )
            append_trust_event(
                "execution_deferred_hitl",
                {
                    "run_id": snipe_rid,
                    "pending_count": len(deferred_snipe_trades),
                    "source": "intraday_sniper",
                },
            )

        if get_execution_mode() == "human_in_loop":
            logger.info(
                "Intraday sniper (human-in-the-loop): queued=%d rejected=%d strict_mode=%s — run: python orchestrator.py execute_pending",
                len(deferred_snipe_trades),
                len(rejected),
                strict_mode,
            )
            for a in deferred_snipe_trades:
                logger.info(
                    "  QUEUED %s shares=%s @ %.2f",
                    a["ticker"],
                    a["shares"],
                    a["entry_price"],
                )
        else:
            logger.info(
                f"Intraday sniper: executed={len(approved)} rejected={len(rejected)} strict_mode={strict_mode}"
            )
            if approved:
                for a in approved:
                    logger.info(f"  APPROVED {a['ticker']} shares={a['shares']} @ {a['entry_price']:.2f} order_id={a['order_id']}")

    elif command in ("spy_swing", "spy-swing"):
        if not is_agent_enabled("spy_intraday_swing"):
            print("Fortress runtime: spy_intraday_swing disabled (config/fortress_runtime.yaml).")
            sys.exit(0)
        argv_rest = sys.argv[2:]
        do_execute = "--execute" in argv_rest
        argv_rest = [a for a in argv_rest if a != "--execute"]
        portfolio_value = get_spy_swing_default_equity_usd()
        if argv_rest:
            try:
                portfolio_value = float(argv_rest[0])
            except ValueError:
                portfolio_value = get_spy_swing_default_equity_usd()

        out = run_spy_swing_cycle(
            shadow_only=not do_execute,
            portfolio_equity=portfolio_value,
            data_dir=DATA_DIR,
        )
        print(json.dumps(out, indent=2, default=str))

        if do_execute and out.get("suggested_action") == "consider_long" and out.get("execute_ready"):
            if out.get("shares", 0) < 1:
                logger.info("spy_swing: execute skipped — shares < 1")
                sys.exit(0)
            if any(str(p.get("ticker", "")).upper() == "SPY" for p in load_positions()):
                logger.info("spy_swing: execute skipped — SPY already in positions.json")
                sys.exit(0)
            risk_status = get_risk_status()
            strict_mode = bool(risk_status.get("circuit_breaker_active")) or int(
                risk_status.get("consecutive_losses") or 0
            ) >= 2
            account_info = get_account_info()
            if not account_info:
                logger.error("spy_swing: no Alpaca account; cannot execute")
                sys.exit(1)
            entry_price = float(out.get("reference_price") or 0)
            shares = int(out["shares"])
            position_value = shares * entry_price
            if account_info.get("buying_power", 0) < position_value * BUYING_POWER_BUFFER:
                logger.error("spy_swing: insufficient buying power")
                sys.exit(1)
            current_positions = load_positions()
            portfolio_data = build_portfolio_data(current_positions, portfolio_value)
            new_position = {
                "ticker": "SPY",
                "size": shares,
                "value": position_value,
                "sector": "ETF",
            }
            risk_check = check_risk_limits(portfolio_data, new_position, strict_mode=strict_mode)
            if not risk_check.get("approved"):
                logger.error("spy_swing: risk_guardian rejected: %s", risk_check.get("reason"))
                sys.exit(1)
            if "adjusted_size" in risk_check:
                shares = int(risk_check["adjusted_size"])
                position_value = shares * entry_price
            order_result = execute_buy_order("SPY", shares, entry_price)
            order_result = _refresh_order_result(order_result)
            if order_result.get("success") and _order_is_filled(order_result):
                add_position(
                    {
                        "ticker": "SPY",
                        "shares": shares,
                        "entry_price": entry_price,
                        "entry_date": datetime.now().isoformat(),
                        "order_id": order_result.get("order_id"),
                        "sector": "ETF",
                        "stop_loss_pct": -0.0035,
                        "take_profit_pct": 0.004,
                        "tiers_sold": {"tier1": False, "tier2": False, "tier3": False},
                        "source": "spy_intraday_swing",
                    }
                )
                logger.info(
                    "spy_swing: executed SPY shares=%s order_id=%s",
                    shares,
                    order_result.get("order_id"),
                )
            else:
                logger.error("spy_swing: order failed: %s", order_result.get("error"))
                sys.exit(1)
        elif do_execute and out.get("suggested_action") == "consider_short":
            logger.info("spy_swing: short signal — execution not wired (shadow only); see agent sketch")

    elif command == "headline_event":
        if not is_agent_enabled("headline_event"):
            print("Fortress runtime: headline_event disabled (config/fortress_runtime.yaml).")
            sys.exit(0)
        from agents.headline_event_agent import run_headline_event_cycle

        root = Path(__file__).resolve().parent
        fp = None
        if len(sys.argv) > 2 and sys.argv[2] == "--fixture":
            fp = root / "tests" / "fixtures" / "headline_event_sample.json"
        out = run_headline_event_cycle(fixture_path=fp)
        print(json.dumps(out, indent=2))
        if not out.get("ok"):
            sys.exit(1)
        sys.exit(0)

    else:
        print(f"Unknown command: {command!r}", file=sys.stderr)
        print("Run: python3 orchestrator.py   (no arguments) for usage.", file=sys.stderr)
        if "verify" in command and "learn" in command:
            print(
                "Hint: If you meant verify_learning, deploy the latest trading-bot from your Mac "
                "(rsync does not update git metadata; pull orchestrator.py with the verify_learning block).",
                file=sys.stderr,
            )
        sys.exit(2)

