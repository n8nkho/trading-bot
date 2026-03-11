"""
No-Trade Diagnostic Agent

Analyzes logs and market data to determine why the bot has not picked (or executed)
opportunities over the past week. Produces 2-5 actionable findings for the Command Center.
Runs when the week had zero or very few executed trades.

Output: data/no_trade_findings.json (consumed by Command Center).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DATA_DIR = Path("data")
LOGS_DIR = Path("logs")
OUTPUT_FILE = DATA_DIR / "no_trade_findings.json"

logging.basicConfig(
    filename=LOGS_DIR / "no_trade_analyzer.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Only produce findings when executed trades in the period are at or below this
MAX_EXECUTED_TO_REPORT = 2


def _read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _load_recent_daily_signals(days: int = 7) -> list[dict]:
    """Load daily_signals from the last N days."""
    pattern = list(DATA_DIR.glob("daily_signals_*.json"))
    pattern.sort(key=lambda p: p.name, reverse=True)
    out = []
    cutoff = datetime.now() - timedelta(days=days)
    for p in pattern:
        try:
            s = p.stem.replace("daily_signals_", "")
            if len(s) == 8:
                d = datetime.strptime(s, "%Y%m%d")
                if d >= cutoff:
                    data = _read_json(p, {})
                    data["_file_date"] = d.isoformat()
                    data["_file"] = p.name
                    out.append(data)
        except Exception as e:
            logger.debug("Skip %s: %s", p.name, e)
    return out


def _tail_log(path: Path, lines: int = 500) -> str:
    try:
        if not path.exists():
            return ""
        with open(path) as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except Exception:
        return ""


def _count_rejection_reasons(signals: list[dict]) -> dict[str, int]:
    """Aggregate rejection reasons from rejected_trades and skipped (from orchestrator log)."""
    reasons: dict[str, int] = {}
    for s in signals:
        for r in s.get("rejected_trades", []):
            reason = (r.get("reason") or "unknown").strip()
            if "confidence" in reason.lower():
                reason = "confidence below threshold"
            elif "drop" in reason.lower() or "criteria" in reason.lower():
                reason = "drop/RSI/volume criteria"
            elif "price" in reason.lower():
                reason = "price/position size"
            elif "risk" in reason.lower():
                reason = "risk limit"
            elif "limit" in reason.lower() or "position" in reason.lower():
                reason = "position/daily limit"
            reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def _parse_screener_rejections(log_text: str) -> dict[str, int]:
    """Count screener log rejections by type (drop, RSI, volume)."""
    drop_rej = len(re.findall(r"Rejected:.*[Dd]rop criteria", log_text))
    rsi_rej = len(re.findall(r"Rejected:.*RSI criteria", log_text))
    vol_rej = len(re.findall(r"Rejected:.*volume criteria", log_text))
    out = {}
    if drop_rej:
        out["drop criteria"] = drop_rej
    if rsi_rej:
        out["RSI criteria"] = rsi_rej
    if vol_rej:
        out["volume criteria"] = vol_rej
    return out


def _get_market_context() -> dict:
    """Current regime and optional VIX/SPY context."""
    regime_data = _read_json(DATA_DIR / "market_regime.json", {})
    regime = (regime_data.get("regime") or "UNKNOWN").upper()
    vix = regime_data.get("vix")
    return {"regime": regime, "vix": vix}


def run_no_trade_analyzer(days: int = 7) -> dict:
    """
    Analyze why the bot had no or few trades in the last `days` days.
    Returns dict with 'findings' (2-5 items: title, body, action, severity), 'timestamp', 'period'.
    """
    findings: list[dict] = []
    signals = _load_recent_daily_signals(days)
    if not signals:
        result = {
            "timestamp": datetime.now().isoformat(),
            "period_days": days,
            "findings": [{
                "title": "No screening data for the week",
                "body": "No daily_signals_*.json found for the last {} days. Screenings may not have run.".format(days),
                "action": "Check cron and logs/screener.log; run orchestrator.py screen manually.",
                "severity": "medium",
            }],
        }
        _write_output(result)
        return result

    total_candidates = sum(s.get("candidates_found", 0) for s in signals)
    total_approved = sum(len(s.get("approved_trades", [])) for s in signals)
    total_executed = total_approved  # approved_trades are what we executed (or attempted)
    zero_candidate_runs = sum(1 for s in signals if s.get("candidates_found", 0) == 0)
    runs_with_candidates = len(signals) - zero_candidate_runs

    # Only report when we had few or no executions (so findings are relevant)
    if total_executed > MAX_EXECUTED_TO_REPORT:
        result = {
            "timestamp": datetime.now().isoformat(),
            "period_days": days,
            "total_signals": len(signals),
            "total_candidates": total_candidates,
            "total_executed": total_executed,
            "findings": [],  # No findings when bot is trading
        }
        _write_output(result)
        return result

    ctx = _get_market_context()
    regime = ctx.get("regime", "UNKNOWN")
    vix = ctx.get("vix")

    # 1) No candidates at all in most runs
    if zero_candidate_runs >= len(signals) // 2 and len(signals) >= 2:
        findings.append({
            "title": "Most screening runs found zero candidates",
            "body": "In the last {} days, {} of {} runs had 0 candidates. Filters (drop 5-15%%, RSI <40, volume >1.5x) may be too strict for current market volatility.".format(
                days, zero_candidate_runs, len(signals)),
            "action": "In RISK_ON consider allowing RSI up to 42 or drop band to -3%% to -12%%. Keep stop loss and volume filters unchanged.",
            "severity": "medium",
        })

    # 2) Candidates found but none executed
    if total_candidates > 0 and total_executed == 0:
        rejection_reasons = _count_rejection_reasons(signals)
        top_reason = ""
        if rejection_reasons:
            top = max(rejection_reasons.items(), key=lambda x: x[1])
            top_reason = " Top skip reason: {} ({}x).".format(top[0], top[1])
        findings.append({
            "title": "Candidates found but no trades executed",
            "body": "{} total candidates across {} runs but 0 executed. Possible causes: confidence threshold (0.70 or 0.66 dry-spell), risk/position limits, or daily profit target already reached.{}".format(
                total_candidates, len(signals), top_reason),
            "action": "Review orchestrator.log for 'Skipped' and 'Daily profit target'; check data/daily_realized_pnl.jsonl and risk_status.json.",
            "severity": "medium",
        })

    # 3) Regime reduced opportunity (RISK_OFF / CRASH)
    if regime in ("RISK_OFF", "CRASH") and total_executed <= 1:
        vix_str = " VIX={:.1f}.".format(vix) if vix is not None else ""
        findings.append({
            "title": "Regime {} reduced auto-trade capacity".format(regime),
            "body": "Market regime was {} this week. Max auto-trades per day and position size are reduced (0.5x in RISK_OFF, 0.25x in CRASH).{} Fewer screenings may qualify.".format(regime, vix_str),
            "action": "Expected behavior for capital preservation. To capture more in RISK_OFF, ensure defensive watchlist is used (data/defensive_watchlist.json).",
            "severity": "low",
        })

    # 4) Screener log rejection breakdown (if we have log access)
    screener_log = _tail_log(LOGS_DIR / "screener.log", 800)
    if screener_log and zero_candidate_runs > 0:
        rej = _parse_screener_rejections(screener_log)
        if rej:
            total_rej = sum(rej.values())
            parts = ["{} ({}x)".format(k, v) for k, v in sorted(rej.items(), key=lambda x: -x[1])[:3]]
            findings.append({
                "title": "Screener rejections by filter",
                "body": "Recent screener log: {} total rejections. Breakdown: {}.".format(total_rej, ", ".join(parts)),
                "action": "If drop criteria dominate, consider slight widen in RISK_ON (e.g. drop_max -3%%). If RSI/volume dominate, keep strict (quality over quantity).",
                "severity": "low",
            })

    # 5) Low volatility / no panic
    if zero_candidate_runs == len(signals) and vix is not None and vix < 18:
        findings.append({
            "title": "Low volatility week; no panic selloffs",
            "body": "VIX was {:.1f} and no screening run found candidates. The strategy looks for 5-15% drops with RSI <40; in calm markets such setups are rare.".format(vix),
            "action": "No change needed. Wait for volatility or run other strategies (momentum, smart money) that don't require panic drops.",
            "severity": "low",
        })

    # Cap at 5 and order by severity (high first)
    severity_order = {"high": 0, "medium": 1, "low": 2}
    findings = sorted(findings, key=lambda x: severity_order.get(x.get("severity", "low"), 2))[:5]

    result = {
        "timestamp": datetime.now().isoformat(),
        "period_days": days,
        "total_signals": len(signals),
        "total_candidates": total_candidates,
        "total_executed": total_executed,
        "regime": regime,
        "findings": findings,
    }
    _write_output(result)
    logger.info("Wrote %d findings to %s", len(findings), OUTPUT_FILE)
    return result


def _write_output(data: dict) -> None:
    try:
        DATA_DIR.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error("Failed to write %s: %s", OUTPUT_FILE, e)


if __name__ == "__main__":
    run_no_trade_analyzer(7)
