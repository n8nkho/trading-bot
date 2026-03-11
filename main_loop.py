"""
Autonomous Trading Bot - Continuous Monitoring Loop v2
Regime-aware, calendar-biased, pre-mortem gated, barbell-constrained.

Usage:
  python3 main_loop.py            # live mode (paper trading)
  python3 main_loop.py --dry-run  # scan only, no execution
  python3 main_loop.py --regime   # print current regime and exit
"""
import asyncio
import argparse
import logging
import signal
import sys
import json
from datetime import datetime, time as dtime
from pathlib import Path
import pytz

# Logging setup first
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "monitor.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main_loop")

from dotenv import load_dotenv
load_dotenv()

# Core orchestrator
from orchestrator import (
    run_daily_screening_async,
    monitor_positions_async,
    is_market_hours,
    get_account_info,
    execute_buy_order,
    add_position,
    load_positions,
)

# Phase 1 strategies
from agents.pead_agent import scan_pead_opportunities
from agents.squeeze_detector import scan_squeeze_opportunities
from agents.low_bounce_agent import scan_low_bounce_opportunities
from agents.vix_spike_agent import scan_vix_spike_opportunities

# Phase 2 strategies
from agents.bear_playbook import scan_bear_opportunities
from agents.vol_compression_agent import scan_vol_compression_opportunities
from agents.lag_detector import scan_lag_opportunities
from agents.etf_rebalance_agent import scan_etf_rebalance_opportunities
from utils.institutional_detector import scan_institutional_footprints

# Regime + overlays
from agents.regime_classifier import classify_regime, load_last_regime
from agents.risk_guardian import check_circuit_breaker, _load_risk_state, check_risk_limits
from utils.calendar_bias import apply_calendar_bias
from utils.premortem import run_premortem
from utils.barbell import get_barbell_limits, check_active_budget_remaining, log_barbell_status
from utils.notifier import send_alert, alert_trade_executed, alert_circuit_breaker
from utils.strategy_tracker import record_trade_result
from utils.bayesian_tuner import run_bayesian_tuning

ET = pytz.timezone("US/Eastern")

# Timing config
SCAN_INTERVAL_SECS = 60
SCREENING_INTERVAL_MINS = 30
POSITION_MONITOR_MINS = 5
REGIME_REFRESH_MINS = 30
MAX_DAILY_TRADES = 12

PRE_MARKET_START = dtime(4, 0)
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)
AFTER_HOURS_END = dtime(20, 0)

# Mutable loop state
state = {
    "last_screening": None,
    "last_position_check": None,
    "last_regime_refresh": None,
    "daily_trade_count": 0,
    "current_day": None,
    "regime": None,
}

# Strategy function map (name -> callable)
STRATEGY_MAP = {
    "pead":                   scan_pead_opportunities,
    "squeeze":                scan_squeeze_opportunities,
    "low_bounce":             scan_low_bounce_opportunities,
    "vix_spike":              scan_vix_spike_opportunities,
    "bear_playbook":          scan_bear_opportunities,
    "vol_compression":        scan_vol_compression_opportunities,
    "lag_detector":           scan_lag_opportunities,
    "etf_rebalance":          scan_etf_rebalance_opportunities,
    "institutional":          scan_institutional_footprints,
}


def is_trading_session():
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return PRE_MARKET_START <= t <= AFTER_HOURS_END


def minutes_since(ts):
    if ts is None:
        return 9999.0
    return (datetime.now() - ts).total_seconds() / 60


async def run_active_strategies(regime_data, dry_run=False):
    """Run all strategies active in current regime. Returns combined candidates."""
    active = regime_data.get("active_strategies", [])
    logger.info(f"Regime [{regime_data.get('regime', '?')}] active: {active}")

    tasks_dict = {}
    for name, fn in STRATEGY_MAP.items():
        if name in active:
            tasks_dict[name] = asyncio.to_thread(fn)

    if not tasks_dict:
        return []

    names = list(tasks_dict.keys())
    results = await asyncio.gather(*tasks_dict.values(), return_exceptions=True)

    candidates = []
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            logger.error(f"Strategy [{name}] failed: {result}")
        elif result:
            logger.info(f"Strategy [{name}]: {len(result)} candidates")
            candidates.extend(result)

    return candidates


async def execute_candidate(candidate, account_info, dry_run=False):
    """Gate candidate through pre-mortem and risk checks, then execute."""
    ticker = candidate["ticker"]
    entry_price = candidate.get("entry_price", 0.0)
    shares = candidate.get("shares", 1)
    confidence = candidate.get("confidence", 0.60)
    strategy = candidate.get("strategy", "UNKNOWN")

    # 1. Calendar bias
    confidence = apply_calendar_bias(confidence)
    candidate["confidence"] = confidence
    if confidence < 0.60:
        logger.info(f"SKIP {ticker}: confidence {confidence:.2f} below 0.60 after calendar bias")
        return False

    # 2. Pre-mortem Monte Carlo
    pm = run_premortem(ticker, entry_price, shares)
    if not pm["approved"]:
        logger.warning(f"SKIP {ticker}: pre-mortem blocked - {pm['reason']}")
        return False

    # 3. Barbell budget gate
    equity = account_info.get("equity", 50000)
    cash = account_info.get("cash", equity)
    active_value = max(0, equity - cash)
    budget = check_active_budget_remaining(equity, active_value)
    if not budget["budget_available"]:
        logger.warning(f"SKIP {ticker}: barbell budget exhausted (${budget['remaining_budget']:.0f} remaining)")
        return False

    # 4. Risk guardian — pass real positions & real today_pnl
    real_positions = load_positions()
    today_pnl = sum(
        (account_info.get("equity", 0) - account_info.get("last_equity", account_info.get("equity", 0)))
        for _ in [None]  # placeholder; Alpaca equity delta approximates daily P&L
    )
    portfolio_data = {
        "equity": equity,
        "positions": real_positions,
        "today_pnl": account_info.get("today_pnl", 0),
    }
    new_pos = {
        "ticker": ticker,
        "size": shares,
        "value": entry_price * shares,
        "sector": candidate.get("sector", "Unknown"),
    }
    risk = check_risk_limits(portfolio_data, new_pos)
    if not risk["approved"]:
        logger.warning(f"SKIP {ticker}: risk guardian - {risk['reason']}")
        return False

    if dry_run:
        logger.info(
            f"DRY-RUN: {ticker} ({strategy}) {shares}x @ ${entry_price:.2f} | "
            f"conf={confidence:.2f} | tail_loss={pm['worst_5pct_loss']:.1%}"
        )
        return True

    # 5. Execute
    result = await asyncio.to_thread(execute_buy_order, ticker, shares, entry_price)
    if result["success"]:
        logger.info(f"EXECUTED: {ticker} ({strategy}) {shares}x @ ${entry_price:.2f} | order={result.get('order_id')}")
        alert_trade_executed(ticker, "BUY", shares, entry_price, strategy)
        await asyncio.to_thread(add_position, {
            "ticker": ticker,
            "shares": shares,
            "entry_price": entry_price,
            "entry_date": datetime.now().isoformat(),
            "strategy": strategy,
            "order_id": result.get("order_id"),
            "stop_loss_pct": candidate.get("stop_loss_pct", 0.05),
            "take_profit_pct": candidate.get("take_profit_pct", 0.10),
        })
        return True
    else:
        logger.error(f"EXECUTION FAILED: {ticker} - {result.get('error')}")
        return False


async def main_loop(dry_run=False):
    logger.info("=" * 70)
    logger.info("AUTONOMOUS TRADING BOT - CONTINUOUS LOOP v2")
    logger.info(f"Mode: {'DRY-RUN' if dry_run else 'LIVE (paper trading)'}")
    logger.info("=" * 70)

    _load_risk_state()

    regime_data = classify_regime()
    state["regime"] = regime_data
    state["last_regime_refresh"] = datetime.now()
    state["current_day"] = datetime.now(ET).date()

    vix_val = regime_data.get("metrics", {}).get("vix", 0)
    send_alert(
        f"Bot started. Regime: {regime_data['regime']} | VIX={vix_val:.1f}",
        level="INFO"
    )

    while True:
        try:
            now_et = datetime.now(ET)

            # Day rollover
            if now_et.date() != state["current_day"]:
                state["current_day"] = now_et.date()
                state["daily_trade_count"] = 0
                logger.info(f"New day: {state['current_day']} - counters reset, running Bayesian tuner")
                try:
                    tune = run_bayesian_tuning()
                    if tune.get("tuned"):
                        logger.info(f"Bayesian: {len(tune.get('changes', []))} param changes")
                except Exception as e:
                    logger.error(f"Bayesian tuning error: {e}")

            # Outside session
            if not is_trading_session():
                logger.debug(f"Outside session ({now_et.strftime('%H:%M ET')}) - sleeping 5 min")
                await asyncio.sleep(300)
                continue

            # Circuit breaker check
            cb = check_circuit_breaker()
            if not cb["approved"]:
                alert_circuit_breaker(0)
                logger.warning(f"Circuit breaker: {cb['reason']}")
                await asyncio.sleep(SCAN_INTERVAL_SECS)
                continue

            # Daily trade limit
            if state["daily_trade_count"] >= MAX_DAILY_TRADES:
                if is_market_hours() and minutes_since(state["last_position_check"]) >= POSITION_MONITOR_MINS:
                    await monitor_positions_async()
                    state["last_position_check"] = datetime.now()
                await asyncio.sleep(SCAN_INTERVAL_SECS)
                continue

            # Regime refresh
            if minutes_since(state["last_regime_refresh"]) >= REGIME_REFRESH_MINS:
                regime_data = classify_regime()
                state["regime"] = regime_data
                state["last_regime_refresh"] = datetime.now()
                logger.info(f"Regime refreshed: {regime_data['regime']}")

            # Position monitoring
            if is_market_hours() and minutes_since(state["last_position_check"]) >= POSITION_MONITOR_MINS:
                try:
                    await monitor_positions_async()
                    state["last_position_check"] = datetime.now()
                except Exception as e:
                    logger.error(f"Position monitor error: {e}")

            # Full screener (regime must include 'screener')
            screener_active = "screener" in state["regime"].get("active_strategies", [])
            if is_market_hours() and screener_active:
                if minutes_since(state["last_screening"]) >= SCREENING_INTERVAL_MINS:
                    try:
                        await run_daily_screening_async()
                        state["last_screening"] = datetime.now()
                    except Exception as e:
                        logger.error(f"Screener error: {e}")

            # Strategy scans (allowed pre/after market for signal discovery)
            candidates = await run_active_strategies(state["regime"], dry_run=dry_run)

            # Gate actual ORDER EXECUTION to market hours only
            if candidates and not is_market_hours():
                logger.info(f"Outside market hours — {len(candidates)} candidates queued but not executed")
                candidates = []  # discard; strategies will re-find them at open

            if candidates:
                account_info = await asyncio.to_thread(get_account_info)
                if account_info is None:
                    account_info = {"equity": 50000, "cash": 50000, "portfolio_value": 50000}

                log_barbell_status(account_info.get("equity", 50000), 0)

                # Deduplicate by ticker (highest confidence wins)
                seen = {}
                for c in candidates:
                    t = c["ticker"]
                    if t not in seen or c.get("confidence", 0) > seen[t].get("confidence", 0):
                        seen[t] = c

                sorted_candidates = sorted(seen.values(), key=lambda x: x.get("confidence", 0), reverse=True)
                logger.info(f"Evaluating {len(sorted_candidates)} unique candidates...")

                # Load current positions to prevent buying tickers we already hold
                existing_tickers = {p["ticker"] for p in load_positions()}

                for candidate in sorted_candidates:
                    if state["daily_trade_count"] >= MAX_DAILY_TRADES:
                        break
                    ticker = candidate["ticker"]
                    if ticker in existing_tickers:
                        logger.info(f"SKIP {ticker}: position already exists (dedup guard)")
                        continue
                    executed = await execute_candidate(candidate, account_info, dry_run=dry_run)
                    if executed and not dry_run:
                        state["daily_trade_count"] += 1
                        existing_tickers.add(ticker)  # prevent re-buying same ticker this tick

            logger.debug(
                f"Tick done. Trades: {state['daily_trade_count']}/{MAX_DAILY_TRADES}. "
                f"Regime: {state['regime'].get('regime', '?')}. Sleep {SCAN_INTERVAL_SECS}s."
            )
            await asyncio.sleep(SCAN_INTERVAL_SECS)

        except asyncio.CancelledError:
            logger.info("Cancelled - shutting down")
            break
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt - shutting down")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
            await asyncio.sleep(30)


def handle_shutdown(signum, frame):
    logger.info(f"Signal {signum} - shutting down")
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trading bot continuous loop v2")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, no execution")
    parser.add_argument("--regime", action="store_true", help="Print current regime and exit")
    args = parser.parse_args()

    if args.regime:
        r = classify_regime()
        print(json.dumps(r, indent=2))
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        asyncio.run(main_loop(dry_run=args.dry_run))
    except KeyboardInterrupt:
        logger.info("Shutdown complete")
