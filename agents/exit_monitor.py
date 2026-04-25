import logging
import threading
import yfinance as yf
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.local_llm import call_llm
from agents.llm_reasoning_engine import LLMReasoningEngine
from agents.screener_agent import get_news_headlines
from utils.option_contract_schema import normalize_option_position
from utils.runtime_config import get_llm_config
from utils.exit_trailing_state import activate_after_tier1, get_state as get_trailing_state, update_peak
from agents.performance_analyzer import track_outcome
from utils.llm_decision_tracker import get_llm_decision_tracker
from agents.llm_learning_agent import LLMLearningAgent

logging.basicConfig(
    filename='logs/exit_monitor.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
_LLM_ENGINE: LLMReasoningEngine | None = None


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


def record_llm_outcome_after_sell_all_fill(signal: dict, pos: dict | None) -> None:
    """
    After a broker-confirmed SELL_ALL fill, update decisions_log + llm_decisions.jsonl outcome
    and optionally run LLMLearningAgent in a background thread.

    Call this only when the exit order is filled (e.g. from orchestrator after execute_sell_order).
    Do not call from evaluate_exit / check_option_exit alone — those are pre-trade signals only.
    """
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
            logger.info("Recorded LLM outcome for signal_id=%s (%s)", signal_id, pos.get("ticker"))

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
        logger.warning("Closed-trade / LLM outcome recording failed: %s: %s", type(e).__name__, e)


# --- LLM OUTCOME RECORDING (ARCHITECTURE) ---
# ADDED: Single production exit path for llm_decisions.jsonl outcomes:
#   orchestrator.monitor_positions_async -> execute_exit (filled SELL_ALL)
#   -> orchestrator._record_closed_trade_and_llm_learning
#   -> record_llm_outcome_after_sell_all_fill(signal, pos) [THIS MODULE]
# Outcomes use signal_id (linked at BUY via link_signal(llm_decision_id, signal_id)), NOT raw ticker.
# evaluate_exit / check_option_exit / create_exit_decision only emit signals — no broker fill here.
# Total broker-confirmed exit points wired for LLM outcomes: 1 (record_llm_outcome_after_sell_all_fill).


def _get_llm_engine() -> LLMReasoningEngine:
    global _LLM_ENGINE
    if _LLM_ENGINE is None:
        _LLM_ENGINE = LLMReasoningEngine()
    return _LLM_ENGINE

# Exit Configuration
STOP_LOSS_PCT = -0.02  # -2% stop loss
MAX_HOLD_DAYS = 3  # Maximum hold period
POSITION_AGING_GUARD = str(os.getenv("FORTRESS_POSITION_AGING_GUARD", "0")).strip().lower() in {"1", "true", "yes", "on"}
MAX_HOLD_DAYS_LONG = int(os.getenv("FORTRESS_MAX_HOLD_DAYS_LONG", "5"))
MAX_HOLD_DAYS_SHORT = int(os.getenv("FORTRESS_MAX_HOLD_DAYS_SHORT", "2"))

# Default stock take-profit ladder (pnl_pct vs entry as fraction; one tier per monitor pass, in order)
# Tier 1: +0.75% → 30% | Tier 2: +1.5% → 25% | Tier 3: +3% → 25% | Tier 4: +5% → 20% (= 100% over four clips)
BALANCED_STOCK_TIERS = (
    ("tier1", 0.0075, 0.30, "SELL_30%"),
    ("tier2", 0.015, 0.25, "SELL_25%"),
    ("tier3", 0.03, 0.25, "SELL_25%"),
    ("tier4", 0.05, 0.20, "SELL_20%"),
)


def _trailing_stop_fraction() -> float:
    try:
        return max(0.001, float(os.getenv("FORTRESS_TRAILING_STOP_PCT", "0.01") or 0.01))
    except ValueError:
        return 0.01


def _normalize_stock_tiers_sold(position: dict) -> dict:
    ts = position.get("tiers_sold")
    if not isinstance(ts, dict):
        ts = {}
    return {
        "tier1": bool(ts.get("tier1")),
        "tier2": bool(ts.get("tier2")),
        "tier3": bool(ts.get("tier3")),
        "tier4": bool(ts.get("tier4")),
    }

# In-memory cache for option chains to avoid repeated network calls.
_OPTION_CHAIN_CACHE = {}


def _get_option_chain(underlying_ticker: str, expiration_date: str):
    """
    Fetch option chain once per (underlying, expiration) during a run.
    Returns an object with .calls and .puts DataFrames.
    """
    key = (underlying_ticker, str(expiration_date))
    if key in _OPTION_CHAIN_CACHE:
        return _OPTION_CHAIN_CACHE[key]

    stock = yf.Ticker(underlying_ticker)
    chain = stock.option_chain(str(expiration_date))
    _OPTION_CHAIN_CACHE[key] = chain
    return chain

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
        # Canonicalize any option-shaped positions so exit logic doesn't crash.
        try:
            if pos.get('type') == 'OPTION':
                pos = normalize_option_position(pos)
        except Exception:
            # Fail safe: if normalization fails, treat as HOLD (exit monitor should never crash).
            pos = dict(pos)
            pos['type'] = 'STOCK'
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

def check_option_exit(position):
    """
    Option exit logic based on option premium movement.

    Expected position fields:
    - ticker: option contract symbol (used for sell orders)
    - underlying_ticker: underlying equity ticker (used to fetch option chain)
    - entry_premium: premium paid at entry
    - strike: selected strike
    - expiration_date: contract expiration (YYYY-MM-DD)
    - call: True for calls, False for puts
    - qty: number of option contracts remaining
    """
    option_symbol = position['ticker']
    underlying_ticker = position.get('underlying_ticker') or option_symbol
    entry_premium = float(position['entry_premium'])
    qty = int(position.get('qty', 0))
    strike = float(position.get('strike'))
    call = bool(position.get('call', True))

    expiration_date = datetime.fromisoformat(position['expiration_date'])
    
    # Calculate days to expiration (DTE)
    dte = (expiration_date - datetime.now()).days
    logging.info(f"{option_symbol}: Days to expiration (DTE): {dte}")
    
    # Fetch current option premium from the options chain.
    logging.info(f"{option_symbol}: Fetching current option premium from chain...")
    chain = _get_option_chain(underlying_ticker, position["expiration_date"])
    rows = chain.calls if call else chain.puts

    if rows is None or rows.empty:
        logging.warning(f"{option_symbol}: No option chain rows returned")
        return create_hold_decision(option_symbol, "No option chain data available", None, None)

    # Find the row closest to the target strike (float comparisons can be noisy).
    nearest_idx = (rows['strike'] - strike).abs().idxmin()
    row = rows.loc[nearest_idx]

    # Prefer lastPrice; fall back to mid of bid/ask.
    current_premium = row.get('lastPrice')
    try:
        if current_premium is None or (isinstance(current_premium, float) and current_premium != current_premium):  # NaN
            bid = row.get('bid', 0) or 0
            ask = row.get('ask', 0) or 0
            current_premium = (bid + ask) / 2 if (bid and ask) else None
    except Exception:
        current_premium = None

    if current_premium is None:
        logging.warning(f"{option_symbol}: Could not determine current premium (missing last/bid/ask)")
        return create_hold_decision(option_symbol, "Could not determine current premium", None, None)

    current_premium = float(current_premium)
    profit_pct = ((current_premium - entry_premium) / entry_premium) * 100

    logging.info(
        f"{option_symbol}: Entry Premium: ${entry_premium:.4f}, Current Premium: ${current_premium:.4f}, Profit: {profit_pct:.2f}%"
    )
    
    # Check 1: Stop Loss (tight to protect capital)
    OPTION_STOP_LOSS_PCT = -15.0
    if profit_pct <= OPTION_STOP_LOSS_PCT:
        reason = f"Option stop loss triggered: {profit_pct:.2f}% <= {OPTION_STOP_LOSS_PCT:.2f}%"
        logging.warning(f"{option_symbol}: {reason}")
        return create_exit_decision(
            option_symbol, 'SELL_ALL', reason, qty, current_premium, profit_pct, 
            stop_loss=True
        )
    
    # Check 2: Time Exit (close earlier to reduce theta bleed)
    if dte < 10:
        reason = f"Time exit: {dte} DTE < 10"
        logging.info(f"{option_symbol}: {reason}")
        return create_exit_decision(
            option_symbol, 'SELL_ALL', reason, qty, current_premium, profit_pct,
            time_limit=True
        )
    
    # Check 3: Theta Exit (< 5 DTE)
    if dte < 5:
        reason = f"Theta exit: {dte} DTE < 5"
        logging.info(f"{option_symbol}: {reason}")
        return create_exit_decision(
            option_symbol, 'SELL_ALL', reason, qty, current_premium, profit_pct,
            time_limit=True
        )
    
    # Check 4: Tiered Take Profits
    # Tier 3: +100% (sell remaining)
    if profit_pct >= 100:
        reason = f"Option take profit tier 3: {profit_pct:.2f}% >= 100%"
        logging.info(f"{option_symbol}: {reason}")
        return create_exit_decision(
            option_symbol, 'SELL_ALL', reason, qty, current_premium, profit_pct,
            tier='tier3'
        )
    
    # Tier 2: +50% (sell 30%)
    if profit_pct >= 50:
        sell_qty = int(qty * 0.30)
        if sell_qty > 0:
            reason = f"Option take profit tier 2: {profit_pct:.2f}% >= 50%"
            logging.info(f"{option_symbol}: {reason}")
            return create_exit_decision(
                option_symbol, 'SELL_30%', reason, sell_qty, current_premium, profit_pct,
                tier='tier2'
            )
    
    # Tier 1: +25% (sell 50%)
    if profit_pct >= 25:
        sell_qty = int(qty * 0.50)
        if sell_qty > 0:
            reason = f"Option take profit tier 1: {profit_pct:.2f}% >= 25%"
            logging.info(f"{option_symbol}: {reason}")
            return create_exit_decision(
                option_symbol, 'SELL_50%', reason, sell_qty, current_premium, profit_pct,
                tier='tier1'
            )
    
    # No exit conditions met - HOLD
    reason = f"No option exit conditions met (Profit: {profit_pct:.2f}%, DTE: {dte})"
    logging.info(f"{option_symbol}: {reason}")
    return create_hold_decision(option_symbol, reason, current_premium, profit_pct)

def evaluate_exit(position):
    """
    Evaluate exit conditions for a single position.
    
    Args:
        position: Position dict with ticker, entry_price, qty/shares, entry_time/entry_date, tiers_sold
        
    Returns:
        Decision dict with action, reason, sell_qty, current_price, pnl_pct
    """
    ticker = position['ticker']
    entry_price = float(position['entry_price'])
    # Handle both 'qty' and 'shares' keys (Alpaca shorts are negative qty)
    try:
        qty_raw = float(
            position.get('qty') if position.get('qty') is not None else position.get('shares', 0)
        )
    except (TypeError, ValueError):
        qty_raw = 0.0
    is_short = qty_raw < 0
    qty_abs = int(abs(qty_raw))
    if qty_abs <= 0:
        logging.warning("%s: zero position qty — HOLD", ticker)
        return create_hold_decision(ticker, "Zero position size", None, None)
    qty = qty_abs
    # Handle both 'entry_time' and 'entry_date' keys
    entry_time = position.get('entry_time') or position.get('entry_date')
    tiers_sold = _normalize_stock_tiers_sold(position)

    # Parse entry time — default to now if missing/invalid so days_held and LLM context never crash.
    if isinstance(entry_time, str):
        try:
            entry_time = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
        except Exception:
            entry_time = datetime.now()
    elif not isinstance(entry_time, datetime):
        entry_time = datetime.now()
    entry_naive = entry_time.replace(tzinfo=None) if entry_time.tzinfo else entry_time

    # Get current price
    logging.info(f"{ticker}: Fetching current price...")
    stock = yf.Ticker(ticker)
    current_data = stock.history(period="1d", interval="1m")
    
    if len(current_data) == 0:
        logging.warning(f"{ticker}: No current price data available")
        return create_hold_decision(ticker, "No current price data available", None, None)
    
    current_price = current_data['Close'].iloc[-1]
    if is_short:
        pnl_pct = (entry_price - float(current_price)) / entry_price if entry_price else 0.0
    else:
        pnl_pct = (float(current_price) - entry_price) / entry_price if entry_price else 0.0

    logging.info(
        "%s: Entry: $%.2f, Current: $%.2f, P&L: %.2f%% (%s)",
        ticker,
        entry_price,
        float(current_price),
        pnl_pct * 100.0,
        "short" if is_short else "long",
    )

    days_held = max(0, (datetime.now() - entry_naive).days)

    # Short squeeze protection: cover quickly when short P&L degrades sharply intraday.
    if is_short and str(os.getenv("FORTRESS_SHORT_SQUEEZE_GUARD", "1")).strip().lower() in {"1", "true", "yes", "on"}:
        try:
            vol_now = float(current_data["Volume"].iloc[-1] or 0.0)
            vol_avg = float(current_data["Volume"].mean() or 0.0)
            intraday_spike = (vol_now / vol_avg) if vol_avg > 0 else 0.0
            if pnl_pct <= -0.015 and intraday_spike >= 2.0:
                reason = (
                    f"Short squeeze guard: adverse short P&L {pnl_pct*100:.2f}% with volume spike "
                    f"{intraday_spike:.2f}x"
                )
                return create_exit_decision(
                    ticker, "SELL_ALL", reason, qty, current_price, pnl_pct, is_short=True
                )
        except Exception:
            pass

    # LLM-first reasoning path for stock exits (authoritative only for high-confidence EXIT).
    llm_decision = _get_llm_engine().evaluate_exit(
        {
            "ticker": ticker,
            "entry_price": entry_price,
            "current_price": float(current_price),
            "pnl_pct": float(pnl_pct * 100.0),
            "days_held": days_held,
            "qty": qty,
        }
    )
    if llm_decision.get("llm_available"):
        decision = str(llm_decision.get("decision") or "HOLD").upper()
        confidence = float(llm_decision.get("confidence") or 0.0)
        if decision == "EXIT" and confidence >= 0.70:
            reason = f"LLM EXIT ({confidence:.2f}): {llm_decision.get('reasoning')}"
            return create_exit_decision(
                ticker, "SELL_ALL", reason, qty, current_price, pnl_pct, is_short=is_short
            )
        # LLM HOLD/SKIP is advisory only — MUST NOT return here; deterministic rails below must run.
        logging.info(
            "%s: LLM exit advisory HOLD/SKIP (%.2f) — applying deterministic rails: %s",
            ticker,
            confidence,
            (llm_decision.get("reasoning") or "")[:120],
        )

    # Check 1: Stop Loss (-2%)
    if pnl_pct <= STOP_LOSS_PCT:
        reason = f"Stop loss triggered: {pnl_pct*100:.2f}% <= {STOP_LOSS_PCT*100:.2f}%"
        logging.warning(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_price, pnl_pct,
            stop_loss=True, is_short=is_short,
        )

    # Check 2: Trailing stop (1% from peak after tier1; persisted in utils.exit_trailing_state)
    tr = get_trailing_state(ticker)
    if tiers_sold.get("tier1") and not tr.get("active"):
        activate_after_tier1(ticker, float(current_price), is_short=is_short)
        tr = get_trailing_state(ticker)
    if tr.get("active") and float(tr.get("peak") or 0) > 0:
        ref = float(tr["peak"])
        tr_short = bool(tr["is_short"]) if "is_short" in tr else is_short
        cp = float(current_price)
        trail_frac = _trailing_stop_fraction()
        if tr_short:
            if cp < ref:
                update_peak(ticker, cp)
                ref = float(get_trailing_state(ticker).get("peak") or ref)
            rally = (cp - ref) / ref if ref else 0.0
            if rally >= trail_frac:
                reason = (
                    f"Trailing stop (short): price +{rally*100:.2f}% from trough ${ref:.2f} "
                    f"(threshold +{trail_frac*100:.2f}%)"
                )
                logging.info("%s: %s", ticker, reason)
                return create_exit_decision(
                    ticker, "SELL_ALL", reason, qty, current_price, pnl_pct, is_short=True
                )
        else:
            if cp > ref:
                update_peak(ticker, cp)
                ref = float(get_trailing_state(ticker).get("peak") or ref)
            dd = (cp - ref) / ref if ref else 0.0
            if dd <= -trail_frac:
                reason = (
                    f"Trailing stop: {dd*100:.2f}% from peak ${ref:.2f} "
                    f"(threshold -{trail_frac*100:.2f}%)"
                )
                logging.info("%s: %s", ticker, reason)
                return create_exit_decision(
                    ticker, "SELL_ALL", reason, qty, current_price, pnl_pct, is_short=False
                )

    # Check 3: Time Limit (legacy default) or guardrail-specific aging cap.
    max_days = MAX_HOLD_DAYS
    if POSITION_AGING_GUARD:
        max_days = MAX_HOLD_DAYS_SHORT if is_short else MAX_HOLD_DAYS_LONG
    if days_held >= max_days:
        reason = f"Time limit reached: {days_held} days >= {max_days} days"
        logging.info(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_price, pnl_pct,
            time_limit=True, is_short=is_short,
        )

    # Check 4: Negative News
    news_check = check_negative_news(ticker)
    if news_check['has_negative_news']:
        reason = f"Negative news detected: {news_check['summary']}"
        logging.warning(f"{ticker}: {reason}")
        return create_exit_decision(
            ticker, 'SELL_ALL', reason, qty, current_price, pnl_pct,
            negative_news=True, is_short=is_short,
        )

    # Check 5: Tiered take profits (balanced 4-tier ladder)
    for tier_key, thresh, sell_frac, action in BALANCED_STOCK_TIERS:
        if tiers_sold.get(tier_key) or pnl_pct < thresh:
            continue
        sell_qty = max(1, int(qty * sell_frac))
        sell_qty = min(sell_qty, qty)
        if sell_qty <= 0:
            break
        reason = (
            f"Take profit {tier_key}: +{thresh*100:.2f}% threshold, sell {sell_frac*100:.0f}% "
            f"(P&L {pnl_pct*100:.2f}%)"
        )
        logging.info("%s: %s", ticker, reason)
        return create_exit_decision(
            ticker,
            action,
            reason,
            sell_qty,
            current_price,
            pnl_pct,
            tier=tier_key,
            is_short=is_short,
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

        # LLM is advisory/optional. If provider=none (default runtime), skip the
        # blocking Ollama call so the monitor can run autonomously.
        try:
            llm_cfg = get_llm_config() or {}
        except Exception:
            llm_cfg = {}
        llm_provider = str(llm_cfg.get("provider") or "").strip().lower()
        disable_llm = str(os.getenv("EXITMONITOR_DISABLE_LLM", "0") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if disable_llm or llm_provider == "none":
            logging.info(f"{ticker}: Exit-monitor LLM disabled (provider=none or EXITMONITOR_DISABLE_LLM=1).")
            return {"has_negative_news": False, "summary": "LLM disabled (provider=none)."}

        # Call configured provider (ollama/deepseek) only when enabled.
        response = call_llm(prompt, timeout=30)
        
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
                        stop_loss=False, time_limit=False, negative_news=False, tier=None,
                        is_short: bool = False):
    """Create an exit decision dict. is_short=True means cover with BUY (positive sell_qty = shares)."""
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
        'is_short': bool(is_short),
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
    # Module self-test:
    # Exit decisions should be tested using real `data/positions.json` or by
    # providing sample positions from an external harness (no hard-coded tickers here).
    print("Exit monitor self-test: no hard-coded ticker examples in this build.")
