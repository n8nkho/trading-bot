"""
Opportunity Analyzer Agent

Analyzes tickers screened by the system to identify:
- Safe opportunities lost (would have been profitable without breaching stop)
- Strategy and criteria recommendations to improve capture while keeping
  near-zero-loss and high win-rate goals.

Output: data/opportunity_recommendations.json (consumed by Command Center).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DATA_DIR = Path("data")
LOGS_DIR = Path("logs")
OUTPUT_FILE = DATA_DIR / "opportunity_recommendations.json"

logging.basicConfig(
    filename=LOGS_DIR / "opportunity_analyzer.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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
            # Parse date from filename daily_signals_YYYYMMDD.json
            s = p.stem.replace("daily_signals_", "")
            if len(s) == 8:
                d = datetime.strptime(s, "%Y%m%d")
                if d >= cutoff:
                    data = _read_json(p, {})
                    data["_file_date"] = d.isoformat()
                    data["_file_signal_date"] = d  # datetime for outcome logging
                    out.append(data)
        except Exception as e:
            logger.debug("Skip %s: %s", p.name, e)
    return out


def _load_signals_for_outcome_logging(max_days_back: int = 90) -> list[dict]:
    """Load daily_signals that are at least 5 days old (so we can compute outcome)."""
    pattern = list(DATA_DIR.glob("daily_signals_*.json"))
    pattern.sort(key=lambda p: p.name, reverse=True)
    out = []
    today = datetime.now().date()
    min_signal_date = today - timedelta(days=max_days_back)
    for p in pattern:
        try:
            s = p.stem.replace("daily_signals_", "")
            if len(s) != 8:
                continue
            d = datetime.strptime(s, "%Y%m%d")
            signal_date = d.date()
            if signal_date < min_signal_date:
                break
            if (signal_date + timedelta(days=5)) > today:
                continue  # not enough forward data yet
            data = _read_json(p, {})
            data["_file_date"] = d.isoformat()
            data["_file_signal_date"] = d
            out.append(data)
        except Exception as e:
            logger.debug("Skip %s: %s", p.name, e)
    return out


OUTCOME_RECORDS_FILE = DATA_DIR / "outcome_records.jsonl"
OUTCOME_DAYS_FORWARD = 5


def _append_outcome_records() -> None:
    """
    Phase 1 self-improving: for each candidate in signals that are 5+ days old,
    compute outcome (safe_win/stop_hit/open) and append to outcome_records.jsonl.
    Skips (ticker, signal_date) already present.
    """
    try:
        existing_keys: set[tuple[str, str]] = set()
        if OUTCOME_RECORDS_FILE.exists():
            with open(OUTCOME_RECORDS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        existing_keys.add((str(rec.get("ticker", "")), str(rec.get("signal_date", ""))))
                    except (json.JSONDecodeError, TypeError):
                        continue

        signals = _load_signals_for_outcome_logging(90)
        new_records: list[dict] = []
        for s in signals:
            signal_dt = s.get("_file_signal_date")
            if not signal_dt:
                continue
            signal_date_str = signal_dt.strftime("%Y-%m-%d") if hasattr(signal_dt, "strftime") else str(signal_dt)[:10]
            regime = s.get("regime") or ""
            candidates = s.get("candidates", [])
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                ticker = c.get("ticker")
                if not ticker:
                    continue
                if (ticker, signal_date_str) in existing_keys:
                    continue
                entry = c.get("current_price") or 0
                if not entry or entry <= 0:
                    # Backfill: old signals may not have current_price; fetch close on signal_date
                    try:
                        import yfinance as yf
                        start = signal_date_str
                        end = (datetime.strptime(signal_date_str, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")
                        hist = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
                        if hist is not None and not hist.empty and "Close" in hist.columns:
                            close_col = hist["Close"]
                            if hasattr(close_col, "iloc"):
                                entry = float(close_col.iloc[0])
                    except Exception:
                        pass
                if not entry or entry <= 0:
                    continue
                drop_pct = c.get("drop_pct")
                rsi = c.get("rsi")
                volume_ratio = c.get("volume_ratio")
                if drop_pct is None and rsi is None:
                    continue
                check = _check_safe_opportunity(ticker, signal_dt, float(entry))
                if not check:
                    continue
                outcome = check.get("outcome", "open")
                outcome_pct = check.get("pct")
                rec = {
                    "ticker": ticker,
                    "signal_date": signal_date_str,
                    "drop_pct": round(float(drop_pct), 2) if drop_pct is not None else None,
                    "rsi": round(float(rsi), 2) if rsi is not None else None,
                    "volume_ratio": round(float(volume_ratio), 2) if volume_ratio is not None else None,
                    "regime": regime,
                    "outcome": outcome,
                    "outcome_pct": round(float(outcome_pct), 2) if outcome_pct is not None else None,
                }
                new_records.append(rec)
                existing_keys.add((ticker, signal_date_str))

        if new_records:
            DATA_DIR.mkdir(exist_ok=True)
            with open(OUTCOME_RECORDS_FILE, "a") as f:
                for rec in new_records:
                    f.write(json.dumps(rec) + "\n")
            logger.info("Outcome logging: appended %d records to %s", len(new_records), OUTCOME_RECORDS_FILE)
    except Exception as e:
        logger.exception("Outcome logging failed: %s", e)


def _check_safe_opportunity(ticker: str, signal_date: datetime, entry_price: float) -> dict | None:
    """
    Check if buying at entry_price on signal_date would have been a "safe" win
    (price did not first fall 4% before rising 5% in the next 5 trading days).
    Uses yfinance; returns a small result dict or None.
    """
    try:
        import yfinance as yf
        start = signal_date.strftime("%Y-%m-%d")
        end = (signal_date + timedelta(days=10)).strftime("%Y-%m-%d")
        hist = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
        if hist is None or hist.empty or len(hist) < 2:
            return None
        hist = hist.sort_index()
        # First bar is signal day; we care about subsequent bars
        opens = hist["Open"]
        highs = hist["High"]
        lows = hist["Low"]
        closes = hist["Close"]
        stop_pct = -4.0
        target_pct = 5.0
        for i in range(1, min(len(hist), 6)):
            low = float(lows.iloc[i])
            high = float(highs.iloc[i])
            close = float(closes.iloc[i])
            pct_from_entry = (close - entry_price) / entry_price * 100.0
            drawdown = (low - entry_price) / entry_price * 100.0
            if drawdown <= stop_pct:
                return {"ticker": ticker, "outcome": "stop_hit", "pct": pct_from_entry}
            if pct_from_entry >= target_pct:
                return {"ticker": ticker, "outcome": "safe_win", "pct": pct_from_entry}
        last_close = float(closes.iloc[-1])
        pct = (last_close - entry_price) / entry_price * 100.0
        return {"ticker": ticker, "outcome": "open", "pct": pct}
    except Exception as e:
        logger.debug("%s: check failed %s", ticker, e)
        return None


def run_opportunity_analysis() -> dict:
    """
    Analyze recent screenings and produce recommendations.

    Returns dict with keys: timestamp, recommendations (list), opportunities_lost (list),
    summary (dict).
    """
    logger.info("=" * 80)
    logger.info("OPPORTUNITY ANALYZER - START")
    logger.info("=" * 80)

    result = {
        "timestamp": datetime.now().isoformat(),
        "recommendations": [],
        "opportunities_lost": [],
        "summary": {},
    }

    try:
        signals = _load_recent_daily_signals(7)
        if not signals:
            result["recommendations"].append({
                "title": "No recent screening data",
                "body": "Run daily screening at least once to enable opportunity analysis.",
                "action": "Schedule or run orchestrator.py screen.",
                "severity": "low",
            })
            result["summary"] = {"signals_analyzed": 0}
            _save(result)
            return result

        total_candidates = sum(s.get("candidates_found", 0) for s in signals)
        total_approved = sum(len(s.get("approved_trades", [])) for s in signals)
        total_executed = sum(len(s.get("executed_trades", [])) for s in signals)
        zero_candidate_runs = sum(1 for s in signals if s.get("candidates_found", 0) == 0)

        result["summary"] = {
            "signals_analyzed": len(signals),
            "total_candidates_found": total_candidates,
            "total_approved": total_approved,
            "total_executed": total_executed,
            "runs_with_zero_candidates": zero_candidate_runs,
        }

        # Safe opportunities lost: sample candidates that were approved but not executed
        safe_wins = []
        for s in signals[:3]:  # last 3 runs only
            ts = s.get("timestamp", "")
            if not ts:
                continue
            try:
                signal_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                signal_dt = datetime.now()
            candidates = s.get("candidates", [])
            executed_tickers = {t.get("ticker") for t in s.get("executed_trades", [])}
            for c in candidates[:5]:
                if not isinstance(c, dict):
                    continue
                ticker = c.get("ticker")
                if not ticker or ticker in executed_tickers:
                    continue
                entry = c.get("current_price") or 0
                if entry <= 0:
                    continue
                check = _check_safe_opportunity(ticker, signal_dt, entry)
                if check and check.get("outcome") == "safe_win":
                    safe_wins.append({"ticker": ticker, "pct": check.get("pct", 0)})
        result["opportunities_lost"] = safe_wins[:20]

        # Recommendations aligned with near-zero-loss and high win rate
        if zero_candidate_runs >= len(signals) // 2 and len(signals) >= 2:
            result["recommendations"].append({
                "title": "Many screenings with zero candidates",
                "body": f"In the last 7 days, {zero_candidate_runs} of {len(signals)} runs had 0 candidates. Criteria may be too tight for current regime.",
                "action": "In RISK_ON consider allowing RSI up to 42 or drop band to -3% to -12%. Keep stop loss and volume filters unchanged.",
                "severity": "low",
            })
        if total_candidates > 0 and total_executed == 0 and total_approved == 0:
            # Surface rejection reasons from most recent run with rejections
            rejection_reasons = []
            for s in signals:
                rejected = s.get("rejected_trades", [])
                if rejected:
                    for r in rejected[:5]:
                        reason = r.get("reason", str(r))[:80]
                        if reason and reason not in rejection_reasons:
                            rejection_reasons.append(reason)
            body = f"Screenings found {total_candidates} candidates but none were approved."
            if rejection_reasons:
                body += f" Top rejection reasons: {'; '.join(rejection_reasons[:3])}."
            else:
                body += " Review confidence threshold and risk limits."
            result["recommendations"].append({
                "title": "Candidates found but none approved",
                "body": body,
                "action": "Check MIN_CONFIDENCE_FOR_AUTO (0.70) and risk_status; consider MIN_CONFIDENCE_DRY_SPELL (0.68) when 3+ runs with 0 approved.",
                "severity": "medium",
            })
        if safe_wins:
            result["recommendations"].append({
                "title": "Safe opportunities lost (backtest sample)",
                "body": f"{len(safe_wins)} ticker(s) in recent runs would have been safe wins (target hit without stop). Examples: " + ", ".join(f"{x['ticker']} ({x['pct']:.1f}%)" for x in safe_wins[:5]),
                "action": "Consider slightly widening entry criteria in the same regime (e.g. RSI 40→42 or volume 1.5x→1.4x) while keeping stop and target unchanged.",
                "severity": "low",
            })
        if total_executed > 0 and total_candidates > total_executed:
            result["recommendations"].append({
                "title": "Execution gap",
                "body": f"Approved {total_approved} but executed {total_executed}. Daily limit or risk limits may have capped fills.",
                "action": "Optional: increase MAX_AUTO_TRADES_PER_DAY slightly if regime supports it; otherwise no change needed.",
                "severity": "low",
            })

        # Always reinforce goals
        result["recommendations"].append({
            "title": "Strategy goals reminder",
            "body": "Keep stop loss at -3% to -4%, scalp ladder 2%/4%/6%, and quality filters (volume, RSI, drop band). Prioritize win rate over frequency.",
            "action": "No action required.",
            "severity": "low",
        })

        # Phase 1 self-improving: append outcome records for candidates with 5+ day forward data
        _append_outcome_records()

        _save(result)
        logger.info("Opportunity analysis complete: %d recommendations", len(result["recommendations"]))
    except Exception as e:
        logger.exception("Opportunity analysis failed: %s", e)
        result["recommendations"] = [{
            "title": "Opportunity analyzer error",
            "body": str(e)[:200],
            "action": "Check logs/opportunity_analyzer.log",
            "severity": "medium",
        }]

    logger.info("=" * 80)
    return result


def _save(result: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    try:
        with open(OUTPUT_FILE, "w") as f:
            json.dump(result, f, indent=2)
    except Exception as e:
        logger.error("Failed to write %s: %s", OUTPUT_FILE, e)


if __name__ == "__main__":
    run_opportunity_analysis()
