#!/usr/bin/env python3
"""
Meta-Strategy Analyzer

Reads existing performance artifacts (decisions, outcomes, agent health)
and emits advisory recommendations only. It does NOT change any live
parameters or trading behavior.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


DATA_DIR = Path("data")
LOGS_DIR = Path("logs")
OUTPUT_FILE = DATA_DIR / "meta_strategy_recommendations.json"


logging.basicConfig(
    filename=LOGS_DIR / "meta_strategy_analyzer.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception:
        return default
    return default


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not path.exists():
        return out
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        out.append(rec)
                except Exception:
                    continue
    except Exception:
        return out
    return out


def run_meta_analysis() -> Dict[str, Any]:
    logger.info("=" * 80)
    logger.info("META-STRATEGY ANALYZER START")
    logger.info("=" * 80)

    decisions = _read_jsonl(DATA_DIR / "decisions_log.jsonl")
    outcomes = _read_jsonl(DATA_DIR / "outcome_records.jsonl")
    health = _read_json(DATA_DIR / "agent_health_snapshot.json", {})

    recs: List[Dict[str, Any]] = []

    # Aggregate win/loss by source strategy where available
    by_strategy: Dict[str, Counter] = defaultdict(Counter)
    for o in outcomes:
        strat = str(o.get("strategy") or o.get("source_strategy") or "unknown")
        outcome = str(o.get("outcome", "open"))
        by_strategy[strat][outcome] += 1

    strategy_summaries: List[Dict[str, Any]] = []
    for strat, cnt in by_strategy.items():
        total = sum(cnt.values())
        safe = cnt.get("safe_win", 0)
        stops = cnt.get("stop_hit", 0)
        if total == 0:
            continue
        strategy_summaries.append(
            {
                "strategy": strat,
                "total": total,
                "safe_wins": safe,
                "stops": stops,
                "safe_win_rate": round(safe / total, 3),
                "stop_rate": round(stops / total, 3),
            }
        )

    strategy_summaries.sort(key=lambda x: (-x["safe_win_rate"], -x["total"]))

    if strategy_summaries:
        top = strategy_summaries[0]
        recs.append(
            {
                "title": f"Top strategy by safe-win rate: {top['strategy']}",
                "body": f"Safe-win rate {top['safe_win_rate']:.1%} over {top['total']} logged outcomes "
                f"(stops {top['stop_rate']:.1%}). Consider keeping this strategy fully enabled.",
                "action": "Review this strategy's parameters; only consider scaling after at least 50+ outcomes.",
                "severity": "low",
            }
        )

    # Highlight any strategy with unusually high stop rate and enough samples
    for s in strategy_summaries:
        if s["total"] < 20:
            continue
        if s["stop_rate"] >= 0.35 and s["safe_win_rate"] < 0.5:
            recs.append(
                {
                    "title": f"Strategy under review: {s['strategy']}",
                    "body": f"Stop rate {s['stop_rate']:.1%} over {s['total']} outcomes; "
                    f"safe-win rate {s['safe_win_rate']:.1%}. This may be too aggressive for near-zero-loss goals.",
                    "action": "Consider throttling this strategy (fewer trades or lower sizing) until further review.",
                    "severity": "medium",
                }
            )
            break

    # Surface any agent-manager issues as productized health hints
    if health:
        cron = health.get("cron_jobs", {})
        stale = cron.get("stale_jobs") or []
        if stale:
            recs.append(
                {
                    "title": "Operational: stale cron jobs detected",
                    "body": "Agent Manager reports stale logs for: " + ", ".join(stale),
                    "action": "Check crontab and logs for the listed jobs. Ensure they are active for full automation.",
                    "severity": "medium",
                }
            )

    # Fallback recommendation if we have little or no data yet
    if not recs:
        recs.append(
            {
                "title": "Meta-analysis pending more data",
                "body": "Insufficient outcome data per strategy to make strong recommendations. Continue paper trading.",
                "action": "Re-run meta_strategy_analyzer after at least 50+ logged outcomes.",
                "severity": "low",
            }
        )

    result = {
        "timestamp": datetime.now().isoformat(),
        "recommendations": recs[:5],
        "strategy_summaries": strategy_summaries,
        "decisions_analyzed": len(decisions),
        "outcomes_analyzed": len(outcomes),
    }

    try:
        DATA_DIR.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            json.dump(result, f, indent=2)
        logger.info("Meta-strategy analysis complete: %d recommendations", len(recs))
    except Exception as e:
        logger.error("Failed to write %s: %s", OUTPUT_FILE, e)

    return result


if __name__ == "__main__":
    run_meta_analysis()

