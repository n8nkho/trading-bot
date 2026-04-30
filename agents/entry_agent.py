from __future__ import annotations

import logging
import os
import json
import yfinance as yf
from datetime import datetime
import pytz
import numpy as np
from typing import Any
from pathlib import Path

from utils.runtime_config import get_default_portfolio_usd
from utils.policy_profile import get_profile_bundle
from utils.market_calendar import is_us_equity_rth_open
from utils.trading_guardrails import validate_llm_trade_output
from utils.adaptive_growth_sizing import recommend_size
from utils.uplift_runtime import get_flag_mode
from utils.execution_advisor import advise_execution
from agents.llm_reasoning_engine import LLMReasoningEngine
from utils.llm_decision_tracker import get_llm_decision_tracker

# Log only this module to entry.log — do not use logging.basicConfig on root or
# Flask/werkzeug lines get written to entry.log when the dashboard imports entry_agent.
_log_dir = Path("logs")
_log_dir.mkdir(exist_ok=True)
_entry_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")


def _configure_entry_logging() -> None:
    lg = logging.getLogger(__name__)
    if lg.handlers:
        return
    lg.setLevel(logging.INFO)
    fh = logging.FileHandler(_log_dir / "entry.log")
    fh.setFormatter(_entry_fmt)
    lg.addHandler(fh)
    lg.propagate = False


_configure_entry_logging()
logger = logging.getLogger(__name__)

# Configuration
PORTFOLIO_VALUE = get_default_portfolio_usd()
BASE_POSITION_PCT = 0.05  # 5% of portfolio per position
MAX_POSITION_SIZE = 2000  # Maximum dollars per position
RSI_THRESHOLD = 35  # Extra oversold threshold
# Relax/tighten stabilization via env for operator tuning (paper/prototype safe).
# Condition: current_price > day_low * STABILIZATION_FACTOR
STABILIZATION_FACTOR = float(os.getenv("ENTRY_STABILIZATION_FACTOR", "1.00"))
ENTRY_WINDOW_START = (14, 30)  # 2:30 PM ET
ENTRY_WINDOW_END = (15, 45)  # 3:45 PM ET
_LLM_ENGINE: LLMReasoningEngine | None = None
# Paper mode: lower bar than production; override with FORTRESS_LLM_ENTRY_MIN_CONFIDENCE.
_LLM_MIN_CONF = float(os.getenv("FORTRESS_LLM_ENTRY_MIN_CONFIDENCE", "0.55"))


def _get_llm_engine() -> LLMReasoningEngine:
    global _LLM_ENGINE
    if _LLM_ENGINE is None:
        _LLM_ENGINE = LLMReasoningEngine()
    return _LLM_ENGINE
def _load_analyst_consensus_index(data_dir: Path | None = None) -> dict[str, dict]:
    root = data_dir or Path("data")
    try:
        files = sorted(root.glob("analyst_consensus_*.json"), reverse=True)
        if not files:
            return {}
        with open(files[0], "r", encoding="utf-8") as f:
            doc = json.load(f)
        rows = doc.get("recommendations") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            return {}
        out: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            out[sym] = row
        return out
    except Exception:
        return {}




def _max_new_position_usd_from_policy(portfolio_value: float) -> float:
    """Cap entry notional so risk_guardian (max_position_size_pct) will not reject routine sizes."""
    try:
        pct = float((get_profile_bundle().get("risk") or {}).get("max_position_size_pct", 3.0))
    except (TypeError, ValueError):
        pct = 3.0
    return max(0.0, float(portfolio_value) * (pct / 100.0))


def _entry_window_end_with_extension() -> tuple[int, int]:
    """Extend end of entry window by ENTRY_WINDOW_EXTEND_END_MINUTES (env, default 0)."""
    end_h, end_m = ENTRY_WINDOW_END
    try:
        # Default extension keeps screening -> entry evaluation robust against runtime drift.
        extra = int(os.getenv("ENTRY_WINDOW_EXTEND_END_MINUTES", "15") or "0")
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
            logger.warning(f"{ticker}: No options data available")
            return None

        # Choose the expiration closest to the target DTE (with a broad fallback).
        today = datetime.now()
        parsed: list[tuple[str, int]] = []
        for date_str in options_dates:
            try:
                dte = (datetime.strptime(date_str, "%Y-%m-%d") - today).days
                parsed.append((date_str, int(dte)))
            except Exception:
                continue

        if not parsed:
            logger.warning(f"{ticker}: Could not parse option expirations")
            return None

        # Prefer "nearby" expirations; if none exist in that band, pick nearest overall.
        dte_target_f = float(dte_target)
        band_lo, band_hi = max(7, dte_target_f - 20), dte_target_f + 20
        nearby = [(ds, d) for (ds, d) in parsed if band_lo <= d <= band_hi]
        candidates = nearby if nearby else parsed
        expiration_date = min(candidates, key=lambda x: abs(x[1] - dte_target_f))[0]

        options_chain = stock.option_chain(expiration_date)
        calls = getattr(options_chain, "calls", None)
        if calls is None or getattr(calls, "empty", True):
            return None
        return calls, expiration_date
    except Exception as e:
        logger.error(f"Error fetching options chain for {ticker}: {type(e).__name__}: {str(e)}")
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

    # Pick strike with minimum absolute distance to spot.
    try:
        strikes = calls["strike"]
        atm_idx = (strikes - float(current_price)).abs().idxmin()
        option = calls.loc[atm_idx]
    except Exception:
        # Fallback if the DataFrame shape isn't as expected.
        atm_strike = min(calls["strike"], key=lambda x: abs(float(x) - float(current_price)))
        option = calls[calls["strike"] == atm_strike].iloc[0]

    premium = option.get("lastPrice", None)
    bid = option.get("bid", None)
    ask = option.get("ask", None)
    volume = option.get("volume", 0)

    # Normalize NaNs/None.
    def _to_float(x: Any) -> float | None:
        try:
            if x is None:
                return None
            v = float(x)
            return v
        except Exception:
            return None

    premium_f = _to_float(premium)
    bid_f = _to_float(bid)
    ask_f = _to_float(ask)

    # If lastPrice is missing, prefer ask as a conservative proxy.
    if premium_f is None or premium_f <= 0:
        premium_f = ask_f if ask_f is not None and ask_f > 0 else None

    if premium_f is None or bid_f is None or ask_f is None:
        return None

    return {
        "strike": float(option.get("strike")),
        "premium": premium_f,
        "bid": bid_f,
        "ask": ask_f,
        "volume": float(volume) if volume is not None else 0,
        "expiration": expiration,
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

    premium = float(option["premium"] or 0)
    bid = float(option["bid"] or 0)
    ask = float(option["ask"] or 0)
    strike = float(option["strike"])
    expiration = option["expiration"]
    volume = float(option.get("volume") or 0)

    if premium <= 0 or ask <= 0 or bid <= 0:
        return None

    bid_ask_spread_pct = (ask - bid) / premium * 100 if premium else 999.0
    breakeven = strike + premium
    leverage = current_price / (premium * 100)
    max_contracts = min(3, int(500 / (premium * 100)))
    
    # Relax the "too strict" filters so paper/screening doesn't end up always skipping.
    if (
        bid_ask_spread_pct < 30
        and volume > 50
        and premium * 100 < 900
        and premium > 0.15
    ):
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
    logger.info(f"Evaluating options entry for {ticker}")
    
    # Fetch options chain
    stock = yf.Ticker(ticker)
    options_dates = stock.options
    if not options_dates:
        logger.warning(f"{ticker}: No options data available")
        return create_skip_decision(ticker, "No options data available")
    
    # Select expiration date 30-45 days out
    expiration_date = next((date for date in options_dates if 30 <= (datetime.strptime(date, '%Y-%m-%d') - datetime.now()).days <= 45), None)
    if not expiration_date:
        logger.warning(f"{ticker}: No suitable expiration date found")
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
        logger.warning(f"{ticker}: No suitable options found")
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
        
        logger.info(f"{ticker}: Option trade selected - Strike: {strike}, Expiration: {expiration_date}, Premium: {premium}, Contracts: {contracts}")
        
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
        logger.info(f"{ticker}: Stock trade selected over option")
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
    logger.info(f"Starting entry evaluation for {len(candidates)} candidates")
    logger.info(f"Portfolio value: ${portfolio_value:,.2f}")

    try:
        from agents.performance_analyzer import load_current_params

        _params = load_current_params()
        rsi_effective = float(_params.get("rsi_threshold", RSI_THRESHOLD))
    except Exception:
        rsi_effective = float(RSI_THRESHOLD)

    # Optional operator override (useful when tuning entry stack without code changes).
    # If set and parseable, it replaces whatever `load_current_params()` returned.
    env_rsi = (os.getenv("ENTRY_RSI_THRESHOLD_OVERRIDE") or "").strip()
    if env_rsi:
        try:
            rsi_effective = float(env_rsi)
        except ValueError:
            pass
    
    decisions = []
    adaptive_mode = get_flag_mode("FORTRESS_UPLIFT_ADAPTIVE_SIZING_MODE")
    execution_advisor_mode = get_flag_mode("FORTRESS_UPLIFT_EXECUTION_ADVISOR_MODE")
    deployed_so_far = 0.0
    overnight_so_far = 0.0
    analyst_index = _load_analyst_consensus_index(Path("data"))
    # Entry-window gating must apply to both stock and option decisions.
    # The stock path already enforces this inside `evaluate_single_entry()`;
    # previously the option path could bypass it and attempt option market orders
    # even when the operator runs after-hours.
    in_entry_window = bool(is_entry_window())
    rth_open = bool(is_us_equity_rth_open())
    
    for candidate in candidates:
        ticker = candidate['ticker']
        logger.info(f"Evaluating entry for {ticker}")
        
        try:
            current_price = candidate['current_price']
            stock_confidence = candidate.get('analysis', {}).get('confidence', 0.5)
            signal_mode = "deterministic_only"
            # Agentic boost: if analyst consensus is BUY, lift confidence by +0.10.
            ar = analyst_index.get(str(ticker).upper()) or {}
            rec = str(ar.get("recommendation") or "").strip().upper()
            if rec == "BUY":
                try:
                    base_conf = float(stock_confidence)
                except Exception:
                    base_conf = 0.5
                stock_confidence = min(base_conf + 0.10, 1.0)
                signal_mode = "agentic_signal_boost"
                if isinstance(candidate.get("analysis"), dict):
                    candidate["analysis"]["confidence"] = stock_confidence
                logger.info(
                    "%s: agentic_signal_boost applied (analyst BUY, consensus_score=%s, confidence %.2f -> %.2f)",
                    ticker,
                    ar.get("consensus_score"),
                    base_conf,
                    stock_confidence,
                )
            else:
                logger.info("%s: deterministic_only path (analyst recommendation=%s)", ticker, rec or "N/A")
            
            stock_roi = stock_confidence * 0.05
            option_trade = evaluate_option_trade(ticker, current_price, stock_confidence)
            
            if option_trade:
                option_roi = stock_confidence * 0.50
                if option_roi > stock_roi * 2:
                    if not in_entry_window:
                        # Match the stock-path reason format so `print_entry_skips`
                        # and audit top reasons stay explainable.
                        current_time_et = get_current_time_et()
                        eh, em = _entry_window_end_with_extension()
                        reason = (
                            f"Outside entry window (current: {current_time_et.strftime('%H:%M')} ET, "
                            f"window: 14:30-{eh:02d}:{em:02d} ET)"
                        )
                        decision = create_skip_decision(ticker, reason)
                        logger.info(f"{ticker}: OPTION gated by entry window - {decision}")
                    elif not rth_open:
                        # Alpaca restricts OPTION *market* orders to regular market hours.
                        decision = create_skip_decision(
                            ticker,
                            "options market orders are only allowed during market hours",
                        )
                        logger.info(f"{ticker}: OPTION gated by RTH market-hours - {decision}")
                    else:
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
                        adaptive = recommend_size(
                            equity_usd=float(portfolio_value),
                            current_price=float(option_trade['premium']) * 100.0,
                            confidence=float(stock_confidence),
                            deployed_usd=float(deployed_so_far),
                            overnight_exposure_usd=float(overnight_so_far),
                            overnight_candidate=True,
                        )
                        decision["adaptive_sizing"] = adaptive
                        decision["overnight_candidate"] = True
                        decision["execution_advisor"] = advise_execution(
                            confidence=float(stock_confidence),
                            volume_ratio=float(candidate.get("volume_ratio") or 1.0),
                            regime_label="UNKNOWN",
                        )
                        if adaptive_mode >= 2:
                            contracts = max(0, int(adaptive.get("recommended_shares") or 0) // 100)
                            decision["contracts"] = contracts
                            decision["position_size"] = round(
                                contracts * float(option_trade["premium"]) * 100.0, 2
                            )
                        if execution_advisor_mode >= 2:
                            decision["order_hint"] = (decision.get("execution_advisor") or {}).get("tactic")
                        decision["signal_mode"] = signal_mode
                        logger.info(f"{ticker}: OPTION decision - {decision}")
                else:
                    decision = evaluate_single_entry(
                        candidate,
                        portfolio_value,
                        rsi_threshold=rsi_effective,
                        deployed_usd=deployed_so_far,
                        overnight_exposure_usd=overnight_so_far,
                        adaptive_mode=adaptive_mode,
                        execution_advisor_mode=execution_advisor_mode,
                    )
                    decision['trade_type'] = 'STOCK'
                    # Do not overwrite SKIP reasons (RSI, window, stabilization, etc.).
                    if decision.get("action") == "BUY":
                        decision["reason"] = "Stock trade offers better ROI"
                    decision["signal_mode"] = signal_mode
                    logger.info(f"{ticker}: STOCK decision - {decision}")
            else:
                decision = evaluate_single_entry(
                    candidate,
                    portfolio_value,
                    rsi_threshold=rsi_effective,
                    deployed_usd=deployed_so_far,
                    overnight_exposure_usd=overnight_so_far,
                    adaptive_mode=adaptive_mode,
                    execution_advisor_mode=execution_advisor_mode,
                )
                decision['trade_type'] = 'STOCK'
                if decision.get("action") == "BUY":
                    decision["reason"] = "No suitable option found (stock path)"
                decision["signal_mode"] = signal_mode
                logger.info(f"{ticker}: STOCK decision - {decision}")
            
            if isinstance(decision, dict):
                decision.setdefault("signal_mode", signal_mode)
                if decision.get("action") == "BUY":
                    try:
                        deployed_so_far += float(decision.get("position_size") or 0.0)
                        if bool(decision.get("overnight_candidate", True)):
                            overnight_so_far += float(decision.get("position_size") or 0.0)
                    except Exception:
                        pass
            decisions.append(decision)
        except Exception as e:
            logger.error(f"Error evaluating {ticker}: {type(e).__name__}: {str(e)}")
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
    logger.info(f"Entry evaluation complete: {buy_count} BUY, {len(decisions) - buy_count} SKIP")
    
    return decisions

def create_skip_decision(ticker, reason, **extra: Any):
    """Create a SKIP decision dict"""
    out: dict[str, Any] = {
        'ticker': ticker,
        'action': 'SKIP',
        'reason': reason,
        'position_size': 0,
        'shares': 0,
        'timestamp': datetime.now().isoformat()
    }
    out.update(extra)
    return out

def evaluate_single_entry(
    candidate,
    portfolio_value,
    *,
    rsi_threshold: float | None = None,
    deployed_usd: float = 0.0,
    overnight_exposure_usd: float = 0.0,
    adaptive_mode: int = 0,
    execution_advisor_mode: int = 0,
):
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
    overnight_candidate = bool(candidate.get("overnight_eligible", True))

    # LLM-first reasoning path (replaces deterministic gating when provider is enabled).
    llm_decision = _get_llm_engine().evaluate_trade_opportunity(candidate)
    if llm_decision.get("llm_available"):
        llm_decision_id = get_llm_decision_tracker().record_decision(ticker, llm_decision, dict(candidate))
        llm_action = str(llm_decision.get("decision") or "SKIP").upper()
        llm_conf = float(llm_decision.get("confidence") or 0.0)
        if llm_action == "BUY" and llm_conf >= _LLM_MIN_CONF:
            valid_llm, llm_guard_reason = validate_llm_trade_output(
                ticker,
                str(llm_decision.get("reasoning") or ""),
            )
            if not valid_llm:
                return create_skip_decision(
                    ticker,
                    f"LLM output rejected: {llm_guard_reason}",
                    llm_decision_id=llm_decision_id,
                )
            # Optional tradability sanity-check (fails open when broker metadata unavailable).
            try:
                from utils.alpaca_env import is_alpaca_paper
                from alpaca.trading.client import TradingClient

                key = os.getenv("ALPACA_API_KEY")
                sec = os.getenv("ALPACA_SECRET_KEY")
                if key and sec:
                    tc = TradingClient(key, sec, paper=is_alpaca_paper())
                    asset = tc.get_asset(ticker)
                    if not bool(getattr(asset, "tradable", False)):
                        return create_skip_decision(
                            ticker,
                            "LLM output rejected: non-tradable asset",
                            llm_decision_id=llm_decision_id,
                        )
            except Exception:
                pass
            # Keep sizing bounded by existing policy/risk caps.
            current_price = float(candidate.get("current_price") or 0.0)
            if current_price <= 0:
                return create_skip_decision(
                    ticker, "LLM BUY but current price unavailable", llm_decision_id=llm_decision_id
                )
            base_position = float(portfolio_value) * BASE_POSITION_PCT
            multiplier = float(llm_decision.get("position_size_multiplier") or 1.0)
            multiplier = max(0.8, min(1.2, multiplier))
            policy_cap = _max_new_position_usd_from_policy(portfolio_value)
            position_size = min(base_position * multiplier, MAX_POSITION_SIZE, policy_cap)
            shares = int(position_size / current_price)
            adaptive = recommend_size(
                equity_usd=float(portfolio_value),
                current_price=float(current_price),
                confidence=float(llm_conf),
                deployed_usd=float(deployed_usd),
                overnight_exposure_usd=float(overnight_exposure_usd),
                overnight_candidate=overnight_candidate,
            )
            if adaptive_mode >= 2:
                shares = int(adaptive.get("recommended_shares") or shares)
                position_size = float(adaptive.get("recommended_position_usd") or position_size)
            if shares < 1:
                return create_skip_decision(
                    ticker, "LLM BUY but position size below 1 share", llm_decision_id=llm_decision_id
                )
            return {
                "ticker": ticker,
                "action": "BUY",
                "reason": f"LLM reasoning BUY: {llm_decision.get('reasoning')}",
                "position_size": round(shares * current_price, 2),
                "shares": shares,
                "entry_price": current_price,
                "confidence": llm_conf,
                "timestamp": datetime.now().isoformat(),
                "llm_powered": True,
                "llm_key_factors": llm_decision.get("key_factors") or [],
                "llm_risks": llm_decision.get("risks") or [],
                "llm_learning_hypothesis": llm_decision.get("learning_hypothesis") or "",
                "llm_decision_id": llm_decision_id,
                "adaptive_sizing": adaptive,
                "overnight_candidate": overnight_candidate,
                "execution_advisor": advise_execution(
                    confidence=float(llm_conf),
                    volume_ratio=float(candidate.get("volume_ratio") or 1.0),
                    regime_label="UNKNOWN",
                ),
            }
        # LLM explicitly SKIPs or low-confidence BUY => skip.
        return create_skip_decision(
            ticker,
            f"LLM decision {llm_action}: {llm_decision.get('reasoning')}",
            llm_decision_id=llm_decision_id,
        )
    
    # Fetch current intraday data
    logger.info(f"{ticker}: Fetching intraday data...")
    stock = yf.Ticker(ticker)
    intraday_data = stock.history(period="1d", interval="1m")
    
    if len(intraday_data) == 0:
        logger.warning(f"{ticker}: No intraday data available")
        return create_skip_decision(ticker, "No intraday data available")
    
    # Get current price and day's low
    current_price = intraday_data['Close'].iloc[-1]
    day_low = intraday_data['Low'].min()
    day_high = intraday_data['High'].max()
    
    logger.info(f"{ticker}: Current price: ${current_price:.2f}, Day low: ${day_low:.2f}, Day high: ${day_high:.2f}")
    
    # Check 1: RSI must be extra oversold
    if screener_rsi >= rsi_cap:
        reason = f"RSI not oversold enough ({screener_rsi:.1f} >= {rsi_cap})"
        logger.info(f"{ticker}: {reason}")
        return create_skip_decision(ticker, reason)
    
    logger.info(f"{ticker}: ✓ RSI check passed ({screener_rsi:.1f} < {rsi_cap})")
    
    # Check 2: Price stabilization (current price > low * 1.02)
    stabilization_price = day_low * STABILIZATION_FACTOR
    if current_price <= stabilization_price:
        reason = f"Price not stabilized (${current_price:.2f} <= ${stabilization_price:.2f})"
        logger.info(f"{ticker}: {reason}")
        return create_skip_decision(ticker, reason)
    
    logger.info(f"{ticker}: ✓ Price stabilization check passed (${current_price:.2f} > ${stabilization_price:.2f})")
    
    # Check 3: Time of day (2:30-3:45 PM ET, optional extension via ENTRY_WINDOW_EXTEND_END_MINUTES)
    if not is_entry_window():
        current_time_et = get_current_time_et()
        eh, em = _entry_window_end_with_extension()
        reason = f"Outside entry window (current: {current_time_et.strftime('%H:%M')} ET, window: 14:30-{eh:02d}:{em:02d} ET)"
        logger.info(f"{ticker}: {reason}")
        return create_skip_decision(ticker, reason)
    
    current_time_et = get_current_time_et()
    logger.info(f"{ticker}: ✓ Time window check passed ({current_time_et.strftime('%H:%M')} ET)")
    
    # Size within policy max_position_size_pct, absolute MAX_POSITION_SIZE, and confidence tilt
    policy_cap = _max_new_position_usd_from_policy(portfolio_value)
    base_position = portfolio_value * BASE_POSITION_PCT
    adjusted_position = base_position * confidence
    position_size = min(adjusted_position, MAX_POSITION_SIZE, policy_cap)
    shares = int(position_size / current_price)
    adaptive = recommend_size(
        equity_usd=float(portfolio_value),
        current_price=float(current_price),
        confidence=float(confidence),
        deployed_usd=float(deployed_usd),
        overnight_exposure_usd=float(overnight_exposure_usd),
        overnight_candidate=overnight_candidate,
    )
    if adaptive_mode >= 2:
        shares = int(adaptive.get("recommended_shares") or shares)
        position_size = float(adaptive.get("recommended_position_usd") or position_size)
    
    # Ensure at least 1 share
    if shares < 1:
        reason = f"Position size too small (${position_size:.2f} < 1 share at ${current_price:.2f})"
        logger.info(f"{ticker}: {reason}")
        return create_skip_decision(ticker, reason)
    
    actual_position_size = shares * current_price
    
    logger.info(f"{ticker}: Position sizing - Base: ${base_position:.2f}, Confidence: {confidence:.2f}, Adjusted: ${adjusted_position:.2f}, Final: ${actual_position_size:.2f} ({shares} shares)")
    
    # All checks passed - BUY decision
    decision = {
        'ticker': ticker,
        'action': 'BUY',
        'reason': f'All entry criteria met: RSI={screener_rsi:.1f} (<{rsi_cap}), Price stabilized at ${current_price:.2f}, Time={current_time_et.strftime("%H:%M")} ET',
        'position_size': actual_position_size,
        'shares': shares,
        'entry_price': current_price,
        'confidence': confidence,
        'adaptive_sizing': adaptive,
        'overnight_candidate': overnight_candidate,
        'execution_advisor': advise_execution(
            confidence=float(confidence),
            volume_ratio=float(candidate.get("volume_ratio") or 1.0),
            regime_label="UNKNOWN",
        ),
        'screener_data': {
            'drop_pct': candidate.get('drop_pct'),
            'rsi': screener_rsi,
            'volume_ratio': candidate.get('volume_ratio'),
            'news': candidate.get('news', [])
        },
        'timestamp': datetime.now().isoformat()
    }
    if execution_advisor_mode >= 2:
        decision["order_hint"] = (decision.get("execution_advisor") or {}).get("tactic")
    return decision

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
            logger.info(f"Outside entry window: {current_time.strftime('%H:%M')} ET (window: {start_hour:02d}:{start_min:02d}-{end_hour:02d}:{end_min:02d} ET)")
        
        return in_window
    except Exception as e:
        logger.error(f"Error checking entry window: {type(e).__name__}: {str(e)}")
        return False

def get_current_time_et():
    """Get current time in Eastern Time"""
    et_tz = pytz.timezone('US/Eastern')
    return datetime.now(et_tz)
