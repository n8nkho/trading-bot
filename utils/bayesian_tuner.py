"""
Bayesian Parameter Self-Tuner
Reads recent trade outcomes and nudges screening thresholds toward winning values.
Run daily at session start.
Writes updated params to data/current_params.json.
"""
import json
import logging
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
DATA_DIR = Path("data")
DECISIONS_LOG = DATA_DIR / "decisions_log.jsonl"
PARAMS_FILE = DATA_DIR / "current_params.json"

DEFAULT_PARAMS = {
    "rsi_threshold": 40.0,
    "drop_min": -15.0,
    "drop_max": -5.0,
    "volume_ratio_min": 1.5,
    "confidence_threshold": 0.70,
}
NUDGE_RATE = 0.20
MIN_TRADES_REQUIRED = 8


def load_recent_trades(days=30):
    trades = []
    cutoff = datetime.now() - timedelta(days=days)
    try:
        if not DECISIONS_LOG.exists():
            return []
        with open(DECISIONS_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "")
                    if ts:
                        dt = datetime.fromisoformat(ts)
                        if dt >= cutoff:
                            trades.append(entry)
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"Error loading decisions log: {e}")
    return trades


def _nudge(current, winning_mean, rate=NUDGE_RATE):
    return current + rate * (winning_mean - current)


def run_bayesian_tuning():
    """Read recent trades, nudge params toward winners, save."""
    trades = load_recent_trades(days=30)
    if len(trades) < MIN_TRADES_REQUIRED:
        logger.info(f"Bayesian tuner: {len(trades)} trades, need {MIN_TRADES_REQUIRED} - skipping")
        return {"tuned": False, "reason": f"Insufficient trades ({len(trades)}/{MIN_TRADES_REQUIRED})"}

    winning_trades = [t for t in trades if t.get("pnl_pct", 0) > 0]
    win_rate = len(winning_trades) / len(trades)
    logger.info(f"Bayesian tuner: {len(trades)} trades, win_rate={win_rate:.1%}")

    try:
        current = json.loads(PARAMS_FILE.read_text()) if PARAMS_FILE.exists() else DEFAULT_PARAMS.copy()
    except Exception:
        current = DEFAULT_PARAMS.copy()

    changes = []

    def extract_metric(trade_list, key):
        vals = []
        for t in trade_list:
            metrics = t.get("metrics") or t.get("entry_metrics") or {}
            v = metrics.get(key)
            if v is not None:
                try:
                    vals.append(float(v))
                except Exception:
                    pass
        return vals

    winning_rsi = extract_metric(winning_trades, "rsi")
    if winning_rsi:
        wmean = float(np.mean(winning_rsi))
        new_val = max(25.0, min(50.0, _nudge(current.get("rsi_threshold", 40.0), wmean)))
        if abs(new_val - current.get("rsi_threshold", 40.0)) > 0.5:
            changes.append({"param": "rsi_threshold", "old": current.get("rsi_threshold"), "new": round(new_val, 1)})
            current["rsi_threshold"] = round(new_val, 1)

    winning_drop = extract_metric(winning_trades, "drop_pct")
    if winning_drop:
        wmean = float(np.mean(winning_drop))
        new_val = max(-20.0, min(-3.0, _nudge(current.get("drop_max", -5.0), wmean)))
        if abs(new_val - current.get("drop_max", -5.0)) > 0.3:
            changes.append({"param": "drop_max", "old": current.get("drop_max"), "new": round(new_val, 1)})
            current["drop_max"] = round(new_val, 1)

    winning_vol = extract_metric(winning_trades, "volume_ratio")
    if winning_vol:
        wmean = float(np.mean(winning_vol))
        new_val = max(1.0, min(4.0, _nudge(current.get("volume_ratio_min", 1.5), wmean)))
        if abs(new_val - current.get("volume_ratio_min", 1.5)) > 0.1:
            changes.append({"param": "volume_ratio_min", "old": current.get("volume_ratio_min"), "new": round(new_val, 2)})
            current["volume_ratio_min"] = round(new_val, 2)

    current["last_tuned"] = datetime.now().isoformat()
    current["win_rate_at_tuning"] = round(win_rate, 3)
    current["trades_analyzed"] = len(trades)

    try:
        PARAMS_FILE.write_text(json.dumps(current, indent=2))
        logger.info(f"Bayesian tuner: {len(changes)} changes saved")
    except Exception as e:
        logger.error(f"Failed to save params: {e}")

    return {"tuned": True, "changes": changes, "win_rate": win_rate, "trades_analyzed": len(trades), "new_params": current}
