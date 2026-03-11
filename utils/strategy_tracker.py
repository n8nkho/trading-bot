"""
Per-strategy win rate and P&L tracking.
Writes to data/strategy_performance.json
"""
import json
import logging
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data")
PERF_FILE = DATA_DIR / "strategy_performance.json"
logger = logging.getLogger(__name__)


def load_performance() -> dict:
    try:
        if PERF_FILE.exists():
            with open(PERF_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading strategy performance: {e}")
    return {}


def record_trade_result(strategy: str, ticker: str, pnl_pct: float, entry_price: float, exit_price: float):
    """Record outcome of a completed trade for a given strategy."""
    perf = load_performance()
    if strategy not in perf:
        perf[strategy] = {"trades": 0, "wins": 0, "losses": 0, "total_pnl_pct": 0.0, "history": []}
    s = perf[strategy]
    s["trades"] += 1
    if pnl_pct > 0:
        s["wins"] += 1
    else:
        s["losses"] += 1
    s["total_pnl_pct"] += pnl_pct
    s["win_rate"] = s["wins"] / s["trades"] if s["trades"] > 0 else 0.0
    s["avg_pnl_pct"] = s["total_pnl_pct"] / s["trades"] if s["trades"] > 0 else 0.0
    s["history"].append({
        "timestamp": datetime.now().isoformat(),
        "ticker": ticker,
        "pnl_pct": pnl_pct,
        "entry": entry_price,
        "exit": exit_price
    })
    # Keep only last 100 history entries per strategy
    s["history"] = s["history"][-100:]
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(PERF_FILE, "w") as f:
            json.dump(perf, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving strategy performance: {e}")


def get_strategy_stats(strategy: str) -> dict:
    """Get win rate and avg P&L for a strategy. Returns defaults if no data."""
    perf = load_performance()
    return perf.get(strategy, {
        "trades": 0, "wins": 0, "losses": 0,
        "win_rate": 0.72, "avg_pnl_pct": 0.10,
        "total_pnl_pct": 0.0
    })


def get_all_strategy_stats() -> dict:
    return load_performance()


def should_disable_strategy(strategy: str, min_trades: int = 10, min_win_rate: float = 0.45) -> bool:
    """Returns True if strategy is underperforming and should be disabled."""
    stats = get_strategy_stats(strategy)
    if stats["trades"] < min_trades:
        return False  # Not enough data
    return stats["win_rate"] < min_win_rate
