"""
Pattern Miner Agent (Self-Improving Phase 2)

Reads outcome_records.jsonl from the last 8-12 weeks, discretizes features,
aggregates by (drop_bucket, rsi_bucket, vol_bucket, regime), computes safe_win rate.
Outputs discovered_patterns.json and 0-2 advisory recommendations to
pattern_discovery_recommendations.json (Command Center). No automatic param changes.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DATA_DIR = Path("data")
LOGS_DIR = Path("logs")
OUTCOME_RECORDS = DATA_DIR / "outcome_records.jsonl"
DISCOVERED_PATTERNS_FILE = DATA_DIR / "discovered_patterns.json"
PATTERN_DISCOVERY_REC_FILE = DATA_DIR / "pattern_discovery_recommendations.json"
CURRENT_PARAMS_FILE = DATA_DIR / "current_params.json"

MIN_COUNT_FOR_PATTERN = 8
MIN_SAFE_WIN_RATE = 0.55
WEEKS_LOOKBACK = 12

logging.basicConfig(
    filename=LOGS_DIR / "pattern_miner.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _bucket_drop(pct: float | None) -> str:
    if pct is None:
        return "unknown"
    if pct <= -12:
        return "-15_to_-12"
    if pct <= -9:
        return "-12_to_-9"
    if pct <= -6:
        return "-9_to_-6"
    if pct <= -3:
        return "-6_to_-3"
    return "above_-3"


def _bucket_rsi(rsi: float | None) -> str:
    if rsi is None:
        return "unknown"
    if rsi < 30:
        return "under_30"
    if rsi < 35:
        return "30_to_35"
    if rsi < 40:
        return "35_to_40"
    return "40_plus"


def _bucket_vol(vol: float | None) -> str:
    if vol is None:
        return "unknown"
    if vol < 2:
        return "1.5_to_2"
    if vol < 3:
        return "2_to_3"
    return "over_3"


def _load_outcome_records(weeks: int = 12) -> list[dict]:
    out = []
    cutoff = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    try:
        if not OUTCOME_RECORDS.exists():
            return out
        with open(OUTCOME_RECORDS) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("signal_date", "") >= cutoff and rec.get("outcome"):
                        out.append(rec)
                except (json.JSONDecodeError, TypeError):
                    continue
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to read outcome records: %s", e)
    return out


def _load_current_params() -> dict:
    try:
        if CURRENT_PARAMS_FILE.exists():
            with open(CURRENT_PARAMS_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "drop_min": -15,
        "drop_max": -5,
        "rsi_threshold": 40,
        "volume_ratio_min": 1.5,
    }


def run_pattern_miner(weeks: int = WEEKS_LOOKBACK) -> dict:
    """
    Mine outcome records for high safe_win rate patterns; write discovered_patterns.json
    and 0-2 recommendations to pattern_discovery_recommendations.json.
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "weeks_lookback": weeks,
        "patterns": [],
        "recommendations_count": 0,
    }

    records = _load_outcome_records(weeks)
    if len(records) < MIN_COUNT_FOR_PATTERN:
        logger.info("Insufficient outcome records: %d (need %d+)", len(records), MIN_COUNT_FOR_PATTERN)
        _write_discovered(result["patterns"])
        _write_recommendations([])
        return result

    # Aggregate by (drop_bucket, rsi_bucket, vol_bucket, regime)
    agg: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)  # outcome list per combo
    for rec in records:
        drop_b = _bucket_drop(rec.get("drop_pct"))
        rsi_b = _bucket_rsi(rec.get("rsi"))
        vol_b = _bucket_vol(rec.get("volume_ratio"))
        regime = (rec.get("regime") or "unknown").strip() or "unknown"
        key = (drop_b, rsi_b, vol_b, regime)
        agg[key].append(rec.get("outcome", "open"))

    params = _load_current_params()
    drop_min = params.get("drop_min", -15)
    drop_max = params.get("drop_max", -5)
    rsi_thresh = params.get("rsi_threshold", 40)
    vol_min = params.get("volume_ratio_min", 1.5)

    patterns_out = []
    for (drop_b, rsi_b, vol_b, regime), outcomes in agg.items():
        total = len(outcomes)
        if total < 5:  # noise filter
            continue
        safe_wins = sum(1 for o in outcomes if o == "safe_win")
        rate = safe_wins / total if total else 0
        if total < MIN_COUNT_FOR_PATTERN or rate < MIN_SAFE_WIN_RATE:
            patterns_out.append({
                "pattern": {"drop_bucket": drop_b, "rsi_bucket": rsi_b, "vol_bucket": vol_b, "regime": regime},
                "count": total,
                "safe_win_count": safe_wins,
                "safe_win_rate": round(rate, 3),
                "suggestion": None,
            })
            continue

        # Suggest if pattern is "underused" vs current params
        suggestion = _suggest_action(drop_b, rsi_b, vol_b, regime, drop_min, drop_max, rsi_thresh, vol_min)
        patterns_out.append({
            "pattern": {"drop_bucket": drop_b, "rsi_bucket": rsi_b, "vol_bucket": vol_b, "regime": regime},
            "count": total,
            "safe_win_count": safe_wins,
            "safe_win_rate": round(rate, 3),
            "suggestion": suggestion,
        })

    # Sort by safe_win_rate desc, then count desc
    patterns_out.sort(key=lambda x: (-x["safe_win_rate"], -x["count"]))

    _write_discovered(patterns_out)

    # Build 0-2 recommendations for Command Center (only for patterns with suggestion)
    recs = []
    for p in patterns_out:
        if p.get("suggestion") and len(recs) < 2:
            pat = p["pattern"]
            title = f"Discovered pattern: {pat['drop_bucket']} drop, RSI {pat['rsi_bucket']}, vol {pat['vol_bucket']} ({pat['regime']})"
            body = (
                f"Safe-win rate {p['safe_win_rate']:.1%} over {p['count']} cases. {p['suggestion']}"
            )
            recs.append({
                "title": title,
                "body": body,
                "action": "Review docs/SELF_IMPROVING_PATTERN_DISCOVERY.md; apply only if backtest or manual review supports. No auto-change to params.",
                "severity": "low",
            })

    _write_recommendations(recs)
    result["patterns"] = patterns_out
    result["recommendations_count"] = len(recs)
    logger.info("Pattern miner: %d patterns, %d recommendations", len(patterns_out), len(recs))
    return result


def _suggest_action(
    drop_b: str,
    rsi_b: str,
    vol_b: str,
    regime: str,
    drop_min: int,
    drop_max: int,
    rsi_thresh: int,
    vol_min: float,
) -> str | None:
    """Return suggestion if pattern is not already covered by current params."""
    # Pattern suggests "above -3" drop (e.g. -3 to -5) -> we could widen upper bound in RISK_ON
    if drop_b == "above_-3":
        return "Consider widening drop upper bound in RISK_ON (e.g. -3% to -12%) if regime supports."
    if drop_b == "-6_to_-3" and drop_max < -3:
        return "Pattern in -6% to -3% band; current max drop may be -5%. Consider RISK_ON widen to -3%."
    if rsi_b == "40_plus" and rsi_thresh <= 40:
        return "Pattern includes RSI 40+; consider allowing RSI up to 42 in RISK_ON only."
    # Default: pattern is within or near current band
    return "Pattern within or near current screener band; keep filters as-is or consider optional RISK_ON widen per docs."


def _write_discovered(patterns: list[dict]) -> None:
    try:
        DATA_DIR.mkdir(exist_ok=True)
        with open(DISCOVERED_PATTERNS_FILE, "w") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "patterns": patterns}, f, indent=2)
    except Exception as e:
        logger.error("Failed to write %s: %s", DISCOVERED_PATTERNS_FILE, e)


def _write_recommendations(recs: list[dict]) -> None:
    try:
        DATA_DIR.mkdir(exist_ok=True)
        with open(PATTERN_DISCOVERY_REC_FILE, "w") as f:
            json.dump(
                {"timestamp": datetime.now().isoformat(), "recommendations": recs},
                f,
                indent=2,
            )
    except Exception as e:
        logger.error("Failed to write %s: %s", PATTERN_DISCOVERY_REC_FILE, e)


if __name__ == "__main__":
    run_pattern_miner(WEEKS_LOOKBACK)
