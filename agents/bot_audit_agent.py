"""
Bot Audit Agent

Purpose:
  Provide an operator-facing daily audit of the system against objectives:
    - keep losses near zero (risk discipline / realized PnL health)
    - maintain profit opportunities (signal-to-trade throughput + win rate)
    - surface missed opportunities (screen → entry → risk → execution funnel, HITL backlog)
    - suggest alternative postures (deterministic heuristics vs tape, regime, worst agents)

Key design goals:
  - Read-only trading: no broker order submission.
  - Deterministic ledger/process metrics from local JSON/JSONL + log tails.
  - Optional market tape: delayed quotes via yfinance (benchmark + VIX) when enabled.
  - Safe for Command Center "run anytime": bounded fetch, graceful fallback.
  - Explainable: returns `findings` + `recommendations` with reasons.
"""

from __future__ import annotations

import glob
import json
import os
import time
from collections import Counter
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pytz


ET = pytz.timezone("America/New_York")

# Bot audit “today” = realized activity since 03:00 America/New_York (session anchor).
AUDIT_SESSION_ANCHOR_HOUR_ET = 3
AUDIT_SESSION_ANCHOR_MINUTE_ET = 0


def _safe_localize_et(d: Any, hour: int, minute: int = 0) -> datetime:
    """3 AM ET on date d; handles DST gaps by shifting to 04:00 local if needed."""
    naive = datetime.combine(d, dt_time(hour, minute, 0))
    try:
        return ET.localize(naive, is_dst=None)
    except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
        naive2 = datetime.combine(d, dt_time(4, 0, 0))
        return ET.localize(naive2, is_dst=None)


def _et_audit_window_start(now_et: datetime) -> datetime:
    """
    Start of audit window: 3:00 AM Eastern Time.
    Before 3 AM local, the active window began on the previous calendar day at 3 AM.
    """
    d = now_et.date()
    today_anchor = _safe_localize_et(d, AUDIT_SESSION_ANCHOR_HOUR_ET, AUDIT_SESSION_ANCHOR_MINUTE_ET)
    if now_et < today_anchor:
        prev = d - timedelta(days=1)
        return _safe_localize_et(prev, AUDIT_SESSION_ANCHOR_HOUR_ET, AUDIT_SESSION_ANCHOR_MINUTE_ET)
    return today_anchor


DEFAULT_DATA_DIR = Path("data")
DEFAULT_LOGS_DIR = Path("logs")


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def _parse_timestamp_local_iso(ts: Any) -> datetime | None:
    """
    Parse ISO timestamps from ledger/registry.

    If timestamps have no timezone, interpret them in server-local time.
    For objective comparisons we then derive an ET date string.
    """
    if not ts:
        return None
    try:
        s = str(ts).strip()
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # Interpret as local server time.
            dt = dt.replace(tzinfo=timezone.utc).astimezone(ET)
        else:
            dt = dt.astimezone(ET)
        return dt
    except Exception:
        return None


def _read_text_tail(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
        return txt[-max_chars:]
    except OSError:
        return ""


def _yf_series_close(hist: Any, symbol: str) -> Any:
    """Extract a 1-D close series from yfinance history (handles MultiIndex columns)."""
    if hist is None or hist.empty:
        return None
    close = hist["Close"] if "Close" in hist.columns else None
    if close is None:
        return None
    if hasattr(close, "columns"):
        if symbol in close.columns:
            return close[symbol].dropna()
        return close.iloc[:, 0].dropna()
    return close.dropna()


def _pct_change(last: float, prior: float) -> float | None:
    if prior is None or prior == 0:
        return None
    return round((last / prior - 1.0) * 100.0, 3)


def _tape_trend_label(change_5d_pct: float | None, vs_sma20_pct: float | None) -> str:
    """
    Coarse tape label from recent benchmark performance (heuristic, not advice).
    """
    if change_5d_pct is None:
        return "unknown"
    c5 = float(change_5d_pct)
    vs = float(vs_sma20_pct) if vs_sma20_pct is not None else 0.0
    if c5 >= 1.0 and vs >= -0.75:
        return "uptrend"
    if c5 <= -1.0 and vs <= 0.75:
        return "downtrend"
    if abs(c5) < 0.35 and abs(vs) < 0.35:
        return "sideways"
    return "mixed"


def fetch_market_performance_context(
    *,
    benchmark: str | None = None,
    include_vix: bool = True,
) -> dict[str, Any]:
    """
    Pull delayed daily benchmark (default SPY) and optional ^VIX for audit context.
    Set env BOT_AUDIT_FETCH_MARKET=0 to skip entirely. BOT_AUDIT_BENCHMARK overrides symbol.
    """
    off = os.getenv("BOT_AUDIT_FETCH_MARKET", "1").strip().lower()
    if off in ("0", "false", "no", "off"):
        return {"ok": False, "disabled": True, "reason": "BOT_AUDIT_FETCH_MARKET disabled"}

    sym = (benchmark or os.getenv("BOT_AUDIT_BENCHMARK", "SPY") or "SPY").strip()
    out: dict[str, Any] = {
        "ok": False,
        "benchmark": sym,
        "as_of": None,
        "benchmark_last": None,
        "change_1d_pct": None,
        "change_5d_pct": None,
        "change_20d_pct": None,
        "sma20": None,
        "price_vs_sma20_pct": None,
        "tape_trend": None,
        "vix_last": None,
        "vix_change_1d_pct": None,
        "error": None,
        "source": "yfinance_delayed",
    }

    try:
        import yfinance as yf
    except ImportError:
        out["error"] = "yfinance_not_installed"
        return out

    try:
        hist = yf.download(
            sym,
            period="4mo",
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        ser = _yf_series_close(hist, sym)
        if ser is None or ser.empty:
            out["error"] = "benchmark_no_data"
            return out

        closes = ser.astype(float)
        last = float(closes.iloc[-1])
        out["benchmark_last"] = round(last, 4)
        out["as_of"] = str(closes.index[-1])[:10]

        if len(closes) >= 2:
            out["change_1d_pct"] = _pct_change(last, float(closes.iloc[-2]))
        if len(closes) >= 6:
            out["change_5d_pct"] = _pct_change(last, float(closes.iloc[-6]))
        if len(closes) >= 21:
            out["change_20d_pct"] = _pct_change(last, float(closes.iloc[-21]))
        if len(closes) >= 20:
            sma20 = float(closes.tail(20).mean())
            out["sma20"] = round(sma20, 4)
            out["price_vs_sma20_pct"] = _pct_change(last, sma20)
        out["tape_trend"] = _tape_trend_label(
            out.get("change_5d_pct"),
            out.get("price_vs_sma20_pct"),
        )
        out["ok"] = True

        if include_vix:
            try:
                vh = yf.download(
                    "^VIX",
                    period="2wk",
                    interval="1d",
                    progress=False,
                    auto_adjust=True,
                    threads=False,
                )
                vser = _yf_series_close(vh, "^VIX")
                if vser is not None and not vser.empty:
                    v = vser.astype(float)
                    vl = float(v.iloc[-1])
                    out["vix_last"] = round(vl, 3)
                    if len(v) >= 2:
                        out["vix_change_1d_pct"] = _pct_change(vl, float(v.iloc[-2]))
            except Exception:
                pass
    except Exception as e:
        out["error"] = f"{type(e).__name__}:{e}"
        return out

    return out


def _market_vs_bot_analysis(
    *,
    market: dict[str, Any],
    pnl_session: float,
    loss_status: str,
    profit_status: str,
    total_session_trades: int,
) -> dict[str, Any]:
    """
    Contrast session realized bot outcomes with observable tape (benchmark + VIX).
    """
    findings: list[dict[str, Any]] = []
    if not market.get("ok"):
        err = market.get("error") or market.get("reason") or "unavailable"
        return {
            "summary": f"Market tape context unavailable ({err}). Audit used ledger/hedge inputs only.",
            "findings": [
                {
                    "type": "context",
                    "text": "Enable yfinance (pip install yfinance) and BOT_AUDIT_FETCH_MARKET=1 for benchmark trend context.",
                }
            ],
            "tape_trend": None,
        }

    trend = market.get("tape_trend")
    c5 = market.get("change_5d_pct")
    c1 = market.get("change_1d_pct")
    vix = market.get("vix_last")
    sym = market.get("benchmark") or "SPY"
    c5s = f"{c5}%" if c5 is not None else "n/a"
    c1s = f"{c1}%" if c1 is not None else "n/a"
    summary_parts: list[str] = [
        f"{sym} tape ~5d: {c5s} (1d {c1s}), label={trend}" + (f", VIX {vix}" if vix is not None else "")
    ]

    if trend == "downtrend" and pnl_session < 0 and loss_status != "ok":
        findings.append(
            {
                "type": "align",
                "text": "Session losses overlap a weak/downtrend benchmark window — some drawdown may be systematic beta rather than idiosyncratic execution.",
            }
        )
        summary_parts.append("Losses partly consistent with soft tape.")
    elif trend == "uptrend" and pnl_session < 0 and total_session_trades > 0:
        findings.append(
            {
                "type": "tension",
                "text": "Session realized P&L is negative while the benchmark skewed up over ~5d — review signal quality, fills, and whether names diverged from beta.",
            }
        )
        summary_parts.append("Underperforming a rising tape on realized closes.")
    elif trend == "uptrend" and pnl_session >= 0 and loss_status == "ok":
        findings.append(
            {
                "type": "align",
                "text": "Positive session realized P&L alongside a constructive benchmark trend.",
            }
        )

    if vix is not None and float(vix) >= 25 and profit_status in ("warn", "critical"):
        findings.append(
            {
                "type": "context",
                "text": f"Elevated VIX (~{vix}) with weak opportunity objective — wider spreads/volatility may be throttling execution quality.",
            }
        )

    if total_session_trades == 0 and trend == "uptrend":
        findings.append(
            {
                "type": "opportunity",
                "text": "Benchmark trend constructive but no session ledger fills — opportunity path may be blocked despite tape.",
            }
        )

    return {
        "summary": " ".join(summary_parts),
        "findings": findings,
        "tape_trend": trend,
    }


def _market_backdrop_findings(market: dict[str, Any]) -> list[dict[str, Any]]:
    """Objective-style rows for delayed benchmark / VIX context."""
    out: list[dict[str, Any]] = []
    if not market.get("ok"):
        out.append(
            {
                "metric": "tape_data",
                "value": market.get("error") or market.get("reason") or "unavailable",
                "target": "yfinance delayed daily",
            }
        )
        return out
    out.append({"metric": "benchmark_symbol", "value": market.get("benchmark"), "as_of": market.get("as_of")})
    if market.get("change_5d_pct") is not None:
        out.append({"metric": "benchmark_change_5d_pct", "value": market.get("change_5d_pct")})
    if market.get("change_1d_pct") is not None:
        out.append({"metric": "benchmark_change_1d_pct", "value": market.get("change_1d_pct")})
    if market.get("change_20d_pct") is not None:
        out.append({"metric": "benchmark_change_20d_pct", "value": market.get("change_20d_pct")})
    if market.get("price_vs_sma20_pct") is not None:
        out.append({"metric": "benchmark_vs_sma20_pct", "value": market.get("price_vs_sma20_pct")})
    if market.get("tape_trend"):
        out.append({"metric": "tape_trend_label", "value": market.get("tape_trend")})
    if market.get("vix_last") is not None:
        out.append({"metric": "vix_last", "value": market.get("vix_last")})
    if market.get("vix_change_1d_pct") is not None:
        out.append({"metric": "vix_change_1d_pct", "value": market.get("vix_change_1d_pct")})
    return out


def _load_latest_daily_signals(data_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    pattern = str(data_dir / "daily_signals_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return None, None
    path = Path(files[0])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw, str(path)
    except (OSError, json.JSONDecodeError):
        pass
    return None, str(path)


def _summarize_daily_signals(sig: dict[str, Any] | None, file_path: str | None) -> dict[str, Any]:
    """Funnel metrics from latest orchestrator daily screening artifact."""
    out: dict[str, Any] = {
        "daily_signals_path": file_path,
        "timestamp": None,
        "candidates_found": None,
        "candidates_tickers_sample": [],
        "entry_evaluated": None,
        "entry_buy_count": None,
        "entry_skip_count": None,
        "top_entry_skip_reasons": [],
        "risk_approved_count": None,
        "risk_rejected_count": None,
        "top_risk_reject_reasons": [],
        "approved_trades_count": None,
        "executed_count": None,
        "execution_failed_count": None,
        "pending_human_review": None,
        "execution_mode": None,
        "top_execution_failure_reasons": [],
        "rejected_trades_total": None,
        "screen_error": None,
    }
    if not sig:
        return out
    out["timestamp"] = sig.get("timestamp")
    out["screen_error"] = sig.get("error")
    cands = sig.get("candidates")
    if isinstance(cands, list):
        out["candidates_found"] = len(cands)
        out["candidates_tickers_sample"] = [
            str(c.get("ticker")) for c in cands[:14] if isinstance(c, dict) and c.get("ticker")
        ]
    elif sig.get("candidates_found") is not None:
        try:
            out["candidates_found"] = int(sig["candidates_found"])
        except (TypeError, ValueError):
            pass

    eg = sig.get("entry_gate_summary") if isinstance(sig.get("entry_gate_summary"), dict) else {}
    out["entry_evaluated"] = eg.get("evaluated_candidates")
    out["entry_buy_count"] = eg.get("buy_count")
    out["entry_skip_count"] = eg.get("skip_count")
    out["top_entry_skip_reasons"] = eg.get("top_skip_reasons") or []

    rg = sig.get("risk_gate_summary") if isinstance(sig.get("risk_gate_summary"), dict) else {}
    out["risk_approved_count"] = rg.get("approved_count")
    out["risk_rejected_count"] = rg.get("rejected_count")
    out["top_risk_reject_reasons"] = rg.get("top_rejected_reasons") or []

    ap = sig.get("approved_trades")
    if isinstance(ap, list):
        out["approved_trades_count"] = len(ap)
    exl = sig.get("executed_trades")
    if isinstance(exl, list):
        out["executed_count"] = len(exl)
    fl = sig.get("execution_failures")
    if isinstance(fl, list):
        out["execution_failed_count"] = len(fl)

    exg = sig.get("execution_gate_summary") if isinstance(sig.get("execution_gate_summary"), dict) else {}
    if out["executed_count"] is None and exg.get("executed_count") is not None:
        out["executed_count"] = exg.get("executed_count")
    if out["execution_failed_count"] is None and exg.get("failed_count") is not None:
        out["execution_failed_count"] = exg.get("failed_count")
    out["pending_human_review"] = exg.get("pending_human_review")
    out["execution_mode"] = exg.get("execution_mode")
    out["top_execution_failure_reasons"] = exg.get("top_failure_reasons") or []

    rej = sig.get("rejected_trades")
    if isinstance(rej, list):
        out["rejected_trades_total"] = len(rej)
    return out


def _summarize_pending_queue(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "pending_execution_queue.json"
    out: dict[str, Any] = {"path": str(path), "pending_batches": 0, "pending_trade_count": 0}
    if not path.exists():
        return out
    try:
        from utils.pending_execution_queue import load_batches

        batches = load_batches(data_dir)
    except Exception:
        batches = []
    if not isinstance(batches, list):
        batches = []
    out["pending_batches"] = len(batches)
    n = 0
    for b in batches:
        if isinstance(b, dict):
            t = b.get("trades")
            if isinstance(t, list):
                n += len(t)
    out["pending_trade_count"] = n
    return out


def _decisions_log_session_snapshot(
    path: Path,
    session_start_et: datetime,
    now_et: datetime,
    *,
    max_tail_lines: int = 500,
) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "path": str(path),
        "session_buy_signals": 0,
        "session_skip_signals": 0,
        "session_other_signals": 0,
        "recent_skip_reasons_sample": [],
        "notes": [],
    }
    if not path.exists():
        snap["notes"].append("no_decisions_log")
        return snap
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_tail_lines:]
    except OSError as e:
        snap["notes"].append(f"read_error:{e}")
        return snap
    skip_reasons: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        dec = rec.get("decision")
        if not isinstance(dec, dict):
            continue
        ts = _parse_timestamp_local_iso(
            rec.get("logged_at") or dec.get("timestamp") or rec.get("timestamp")
        )
        if ts is None or ts < session_start_et or ts > now_et:
            continue
        act = str(dec.get("action") or "").upper()
        if act == "BUY":
            snap["session_buy_signals"] += 1
        elif act == "SKIP":
            snap["session_skip_signals"] += 1
            r = dec.get("reason") or dec.get("reasoning") or ""
            if isinstance(r, str) and r.strip():
                skip_reasons.append(r.strip()[:140])
        else:
            snap["session_other_signals"] += 1
    if skip_reasons:
        c = Counter(skip_reasons)
        snap["recent_skip_reasons_sample"] = [f"{t} ({n})" for t, n in c.most_common(5)]
    return snap


def _missed_opportunity_analysis(
    *,
    screen: dict[str, Any],
    pending: dict[str, Any],
    decisions: dict[str, Any],
    session_ledger_trades: int,
) -> dict[str, Any]:
    """
    Heuristic funnel: where candidates died vs broker (no counterfactual PnL).
    """
    findings: list[dict[str, Any]] = []
    cf = screen.get("candidates_found")
    eb = screen.get("entry_buy_count")
    es = screen.get("entry_skip_count")
    approved = screen.get("approved_trades_count")
    executed = screen.get("executed_count") or 0
    risk_rej = screen.get("risk_rejected_count") or 0
    ex_fail = screen.get("execution_failed_count") or 0
    pending_n = pending.get("pending_trade_count") or 0
    phr = screen.get("pending_human_review")

    if pending_n > 0:
        findings.append(
            {
                "type": "hitl_backlog",
                "text": f"{pending_n} approved trade(s) sit in pending_execution_queue.json — largest concrete 'miss' until `orchestrator.py execute_pending` (or UI approval).",
            }
        )
    if phr and int(phr) > 0 and pending_n == 0:
        findings.append(
            {
                "type": "hitl_screen",
                "text": f"Latest screen shows {phr} trade(s) pending human review (execution_gate) — same backlog class as HITL.",
            }
        )

    if cf is not None and eb is not None and cf > 0 and eb == 0 and (es or 0) > 0:
        findings.append(
            {
                "type": "entry_funnel",
                "text": f"Screen produced {cf} candidates but entry gate emitted 0 BUY and {es or 0} SKIP — opportunities missed at entry timing/filters.",
            }
        )

    top_sk = screen.get("top_entry_skip_reasons") or []
    if isinstance(top_sk, list) and top_sk and isinstance(top_sk[0], dict):
        t0 = top_sk[0]
        cnt = int(t0.get("count") or 0)
        if cnt >= 4:
            findings.append(
                {
                    "type": "entry_reason_mass",
                    "text": f"Dominated entry skip reason ({cnt}x): {str(t0.get('reason') or '')[:160]}",
                }
            )

    if approved is not None and approved > 0 and executed == 0 and ex_fail == 0 and pending_n == 0 and (phr or 0) == 0:
        findings.append(
            {
                "type": "execution_gap",
                "text": f"{approved} approved trade(s) in latest daily_signals but 0 executions logged in that run — check execution_mode, broker errors, or whether another process consumed orders.",
            }
        )

    if risk_rej > 0 and (eb or 0) > 0:
        findings.append(
            {
                "type": "risk_gate",
                "text": f"Risk gate rejected {risk_rej} after entry BUY — review top_risk_reject_reasons in daily_signals and risk_guardian limits.",
            }
        )

    if ex_fail > 0:
        findings.append(
            {
                "type": "broker_failures",
                "text": f"{ex_fail} execution failure(s) on latest screen — broker/API friction is a direct missed-fill source.",
            }
        )

    if decisions.get("session_skip_signals", 0) >= 5 and (eb or 0) <= 1:
        findings.append(
            {
                "type": "decision_log",
                "text": f"decisions_log shows {decisions['session_skip_signals']} SKIP vs few BUYs in session — aligns with conservative entry policy or strict gates.",
            }
        )

    if session_ledger_trades == 0 and (cf or 0) >= 3 and executed == 0 and pending_n == 0:
        findings.append(
            {
                "type": "no_realized_despite_pipeline",
                "text": "Candidates existed but no session realized ledger fills and no pending queue — entire stack may be screen-only or exits not yet logged.",
            }
        )

    summary = (
        "; ".join(f["text"] for f in findings)
        if findings
        else "No strong missed-opportunity signals from screening artifacts (or insufficient telemetry)."
    )
    return {
        "summary": summary,
        "findings": findings,
        "inputs": {
            "candidates_found": cf,
            "entry_buy_count": eb,
            "entry_skip_count": es,
            "approved_trades_count": approved,
            "executed_count": executed,
            "pending_trades": pending_n,
        },
    }


def _alternative_strategy_suggestions(
    *,
    worst: list[dict[str, Any]],
    best: list[dict[str, Any]],
    screen: dict[str, Any],
    last_meta: dict[str, Any],
    loss_status: str,
    tape_trend: str | None,
    hedge_regime: str | None,
    consecutive_losses: int | None,
) -> dict[str, Any]:
    """
    Deterministic playbook ideas — not investment advice; for operator review only.
    """
    suggestions: list[dict[str, str]] = []
    regime_u = str(hedge_regime or "").strip().upper()

    if worst and float(worst[0].get("pnl") or 0) < -15 and int(worst[0].get("trades") or 0) >= 2:
        wn = worst[0].get("strategy") or "worst_agent"
        suggestions.append(
            {
                "title": f"Deprioritize {wn}",
                "rationale": f"Largest session drag ({worst[0].get('pnl')}) across {worst[0].get('trades')} realized closes.",
                "action": "Run that agent shadow-only or reduce max positions / size in runtime profile until paper stabilizes.",
            }
        )

    if best and worst and float(best[0].get("pnl") or 0) > 0 and float(worst[0].get("pnl") or 0) < 0:
        bn = best[0].get("strategy") or "best_agent"
        suggestions.append(
            {
                "title": f"Lean into {bn}",
                "rationale": f"Positive realized contribution ({best[0].get('pnl')}) vs negative tail — rebalance attention and capital budget toward the working sleeve.",
                "action": "Increase concurrency or priority for that strategy in orchestrator gates (within risk limits).",
            }
        )

    if last_meta.get("strict_mode") is True:
        suggestions.append(
            {
                "title": "Strict / stressed mode — shrink beta first",
                "rationale": "Screener or risk stack is in strict_mode; chasing the same long book is an alternative mismatch.",
                "action": "Hold capital_preservation profile, refresh fortress hedges, then re-enable incremental size.",
            }
        )

    if tape_trend == "downtrend" and loss_status != "ok":
        suggestions.append(
            {
                "title": "Tape-down alternative sleeve",
                "rationale": "Benchmark trend weak alongside session losses — pure momentum longs are a poor fit.",
                "action": "Emphasize mean-reversion screens, cash raise, or pairs/hedge legs from fortress_report before scaling snipers.",
            }
        )

    if tape_trend == "uptrend" and loss_status != "ok" and (screen.get("entry_buy_count") or 0) <= 1:
        suggestions.append(
            {
                "title": "Tape-up but few BUYs — loosen entry bottleneck",
                "rationale": "Rising tape suggests opportunity set exists; entry_gate may be over-tight vs your objectives.",
                "action": "Review entry thresholds / prefilter in params; run a controlled shadow comparison on skipped names.",
            }
        )

    tops = screen.get("top_entry_skip_reasons") or []
    if tops and isinstance(tops[0], dict) and int(tops[0].get("count") or 0) >= 5:
        r = str(tops[0].get("reason") or "")[:100]
        suggestions.append(
            {
                "title": "Tune the dominant entry skip driver",
                "rationale": f"High concentration of skips for: {r}",
                "action": "Adjust the specific rule (RSI band, spread, liquidity) or move that filter earlier to save compute.",
            }
        )

    if regime_u == "RISK_OFF" and (screen.get("candidates_found") or 0) > 5 and (screen.get("entry_buy_count") or 0) == 0:
        suggestions.append(
            {
                "title": "RISK_OFF regime — alternative alpha path",
                "rationale": "Fortress is defensive; directional equity screen may correctly produce zero BUYs.",
                "action": "Prioritize bond/commodity/FX sleeves from fortress strategies over sniper expansion.",
            }
        )

    if consecutive_losses is not None and int(consecutive_losses) >= 2:
        suggestions.append(
            {
                "title": "Loss streak — flip to validation mode",
                "rationale": "risk_guardian consecutive_losses elevated; adding risk without a new edge is an alternative mismatch.",
                "action": "Paper-only or half-size on new agents until streak resets; run walk-forward / backtest on last week's skips.",
            }
        )

    summary = (
        f"{len(suggestions)} alternative posture idea(s) from funnel + tape + regime heuristics."
        if suggestions
        else "No alternative-strategy heuristics fired (insufficient contrast in data)."
    )
    return {"summary": summary, "suggestions": suggestions[:8]}


def _rollup_gate_attribution(data_dir: Path, *, max_files: int = 12) -> dict[str, Any]:
    """Aggregate skip / risk / execution-failure reasons across recent daily_signals files."""
    pattern = str(data_dir / "daily_signals_*.json")
    files = sorted(glob.glob(pattern), reverse=True)[:max_files]
    skip_counter: Counter[str] = Counter()
    risk_counter: Counter[str] = Counter()
    fail_counter: Counter[str] = Counter()
    totals = {
        "files_scanned": 0,
        "candidates_sum": 0,
        "entry_buy_sum": 0,
        "entry_skip_sum": 0,
        "approved_sum": 0,
        "executed_sum": 0,
    }
    for fp in files:
        try:
            sig = json.loads(Path(fp).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(sig, dict):
            continue
        totals["files_scanned"] += 1
        cands = sig.get("candidates")
        if isinstance(cands, list):
            totals["candidates_sum"] += len(cands)
        eg = sig.get("entry_gate_summary") if isinstance(sig.get("entry_gate_summary"), dict) else {}
        totals["entry_buy_sum"] += int(eg.get("buy_count") or 0)
        totals["entry_skip_sum"] += int(eg.get("skip_count") or 0)
        for row in eg.get("top_skip_reasons") or []:
            if isinstance(row, dict):
                skip_counter[str(row.get("reason") or "")] += int(row.get("count") or 0)
        rg = sig.get("risk_gate_summary") if isinstance(sig.get("risk_gate_summary"), dict) else {}
        for row in rg.get("top_rejected_reasons") or []:
            if isinstance(row, dict):
                risk_counter[str(row.get("reason") or "")] += int(row.get("count") or 0)
        ap = sig.get("approved_trades")
        if isinstance(ap, list):
            totals["approved_sum"] += len(ap)
        exl = sig.get("executed_trades")
        if isinstance(exl, list):
            totals["executed_sum"] += len(exl)
        exg = sig.get("execution_gate_summary") if isinstance(sig.get("execution_gate_summary"), dict) else {}
        for row in exg.get("top_failure_reasons") or []:
            if isinstance(row, dict):
                fail_counter[str(row.get("reason") or "")] += int(row.get("count") or 0)
    return {
        "rollup_files_scanned": totals["files_scanned"],
        "totals": totals,
        "top_skip_reasons_rollup": [{"reason": r, "count": c} for r, c in skip_counter.most_common(8)],
        "top_risk_reject_rollup": [{"reason": r, "count": c} for r, c in risk_counter.most_common(8)],
        "top_execution_failure_rollup": [{"reason": r, "count": c} for r, c in fail_counter.most_common(6)],
    }


def _file_mtime_age_hours(path: Path, now_utc: datetime) -> float | None:
    if not path.exists():
        return None
    try:
        return round((now_utc.timestamp() - path.stat().st_mtime) / 3600.0, 2)
    except OSError:
        return None


def _signal_timestamp_age_hours(ts_raw: Any, now_utc: datetime) -> float | None:
    p = _parse_timestamp_local_iso(ts_raw)
    if p is None:
        return None
    nu = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    pu = p.astimezone(timezone.utc)
    return round((nu - pu).total_seconds() / 3600.0, 2)


def _log_staleness(logs_dir: Path, names: tuple[str, ...], now_utc: datetime) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in names:
        p = logs_dir / name
        out[name] = {
            "exists": p.exists(),
            "age_hours": _file_mtime_age_hours(p, now_utc),
        }
    return out


# Cron often splits screen/monitor/fortress across screener.log, monitor.log, fortress.log
# instead of a single orchestrator.log — audit uses the freshest mtime among these as "core jobs" heartbeat.
_CORE_JOB_LOG_NAMES = (
    "orchestrator.log",
    "screener.log",
    "monitor.log",
    "fortress.log",
)


def _core_jobs_log_freshness(freshness_logs: dict[str, Any]) -> dict[str, Any]:
    ages: list[tuple[str, float]] = []
    for name in _CORE_JOB_LOG_NAMES:
        b = (freshness_logs or {}).get(name) or {}
        if not b.get("exists") or b.get("age_hours") is None:
            continue
        try:
            ages.append((name, float(b["age_hours"])))
        except (TypeError, ValueError):
            continue
    if not ages:
        return {"best_name": None, "best_age_hours": None, "stale_gt_72h": True}
    best_name, best_age = min(ages, key=lambda x: x[1])
    return {
        "best_name": best_name,
        "best_age_hours": round(best_age, 2),
        "stale_gt_72h": bool(best_age > 72.0),
    }


def _pending_age_detail(data_dir: Path, now_utc: datetime) -> dict[str, Any]:
    try:
        from utils.pending_execution_queue import load_batches

        batches = load_batches(data_dir)
    except Exception:
        batches = []
    oldest_utc: datetime | None = None
    for b in batches or []:
        if not isinstance(b, dict):
            continue
        dt = _parse_timestamp_local_iso(b.get("updated_at"))
        if dt is not None:
            du = dt.astimezone(timezone.utc)
            if oldest_utc is None or du < oldest_utc:
                oldest_utc = du
    nu = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    age_h = None
    if oldest_utc is not None:
        age_h = round((nu - oldest_utc).total_seconds() / 3600.0, 2)
    return {"oldest_pending_batch_age_hours": age_h}


def _exit_signals_summary(data_dir: Path, *, max_runs: int = 20) -> dict[str, Any]:
    pattern = str(data_dir / "exit_signals_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return {
            "latest_path": None,
            "action_totals": {},
            "executed_exits_sum": 0,
            "exit_failures_sum": 0,
            "notes": ["no_exit_signals_json"],
        }
    path = Path(files[0])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"latest_path": str(path), "error": str(e)}
    runs = raw.get("runs") if isinstance(raw.get("runs"), list) else [raw]
    action_totals: Counter[str] = Counter()
    ex_sum = 0
    fl_sum = 0
    for run in runs[-max_runs:]:
        if not isinstance(run, dict):
            continue
        sm = run.get("action_summary")
        if isinstance(sm, dict):
            for k, v in sm.items():
                try:
                    action_totals[str(k)] += int(v)
                except (TypeError, ValueError):
                    pass
        ee = run.get("executed_exits")
        if isinstance(ee, list):
            ex_sum += len(ee)
        ef = run.get("exit_failures")
        if isinstance(ef, list):
            fl_sum += len(ef)
    return {
        "latest_path": str(path),
        "runs_window": min(len(runs), max_runs),
        "action_totals": dict(action_totals),
        "executed_exits_sum": ex_sum,
        "exit_failures_sum": fl_sum,
    }


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        o = json.loads(path.read_text(encoding="utf-8"))
        return o if isinstance(o, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _research_backtest_block(data_dir: Path) -> dict[str, Any]:
    """Walk-forward report + illustrative backtest snapshot (paths under data_dir)."""
    wf = _read_json_dict(data_dir / "walk_forward_report.json")
    bt = _read_json_dict(data_dir / "backtest_snapshot.json")
    wf_sum: dict[str, Any] = {}
    if wf:
        wf_sum = {
            "stable": wf.get("stable"),
            "reason": (str(wf.get("reason") or ""))[:240],
            "drift_alert": wf.get("drift_alert"),
        }
    bt_sum: dict[str, Any] = {}
    if bt:
        bt_sum = {
            "ticker": bt.get("ticker"),
            "strategy_total_return": bt.get("strategy_total_return"),
            "buy_hold_total_return": bt.get("buy_hold_total_return"),
            "max_drawdown": bt.get("max_drawdown"),
            "error": bt.get("error"),
        }
    return {
        "walk_forward_path": str(data_dir / "walk_forward_report.json"),
        "walk_forward_summary": wf_sum,
        "backtest_snapshot_path": str(data_dir / "backtest_snapshot.json"),
        "backtest_summary": bt_sum,
    }


def _efficiency_and_policy_snapshot(
    latest_signals: dict[str, Any] | None,
    last_meta: dict[str, Any],
) -> dict[str, Any]:
    eff: dict[str, Any] = {
        "fundamental_cost_last_screen": None,
        "screening_duration_seconds_meta": None,
        "universe_size_meta": None,
    }
    if latest_signals and isinstance(latest_signals, dict):
        fc = latest_signals.get("fundamental_cost")
        if fc is not None:
            eff["fundamental_cost_last_screen"] = fc
    if isinstance(last_meta, dict):
        eff["screening_duration_seconds_meta"] = last_meta.get("screening_duration_seconds")
        eff["universe_size_meta"] = last_meta.get("universe_size")
    env_prof = (os.getenv("TRADING_POLICY_PROFILE") or "").strip() or None
    meta_prof = last_meta.get("policy_profile") if isinstance(last_meta, dict) else None
    drift = None
    if env_prof and meta_prof and str(env_prof).lower() != str(meta_prof).lower():
        drift = f"env TRADING_POLICY_PROFILE={env_prof} vs last_screening_meta policy_profile={meta_prof}"
    return {
        "efficiency": eff,
        "policy_profile_env": env_prof,
        "policy_profile_last_meta": meta_prof,
        "profile_drift_hint": drift,
    }


def _read_current_params_snapshot(data_dir: Path) -> dict[str, Any]:
    p = data_dir / "current_params.json"
    base = {"path": str(p), "loaded": False}
    if not p.exists():
        return base
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return {**base, "error": "not_a_dict"}
        return {
            "path": str(p),
            "loaded": True,
            "rsi_threshold": d.get("rsi_threshold"),
            "stop_loss_pct": d.get("stop_loss_pct"),
            "take_profit_pct": d.get("take_profit_pct"),
            "last_updated": d.get("last_updated"),
        }
    except (OSError, json.JSONDecodeError) as e:
        return {**base, "error": str(e)}


def _map_skip_reason_to_entry_change(reason_raw: str) -> str:
    rl = (reason_raw or "").lower()
    if "window" in rl or "entry window" in rl or ("outside" in rl and "window" in rl):
        return (
            "Entry time window likely blocking BUYs: adjust ENTRY_WINDOW_START/END in agents/entry_agent.py "
            "or run screening inside the allowed ET window (defaults ~2:30–3:45 PM ET)."
        )
    if "rsi" in rl or "oversold" in rl:
        return (
            "RSI / oversold gate: review data/current_params.json rsi_threshold (and screener tier RSI). "
            "Raise slightly only after paper validation — looser RSI admits weaker setups."
        )
    if "spread" in rl or "liquidity" in rl or "volume" in rl:
        return (
            "Liquidity/spread skips: tighten screener min volume in agents/screener_agent.py tiers, "
            "or add max spread check; in high VIX, consider smaller symbols universe."
        )
    if "vix" in rl or "volatility" in rl or "vol" in rl:
        return (
            "Volatility-conditioned skip: tie BUY confidence to VIX or require fresh fortress_report "
            "before entries in strict_mode (orchestrator hedge gate)."
        )
    if "confidence" in rl or "fundamental" in rl:
        return (
            "Confidence/fundamental gate: lower FUNDAMENTAL_CONFIDENCE_THRESHOLD only if cost acceptable, "
            "or bypass fundamentals for shadow paper tests per ticker class."
        )
    return (
        f"Open latest daily_signals JSON → entry_gate top_skip_reasons for full text: {reason_raw[:140]!r}. "
        "Trace matching branch in agents/entry_agent.py evaluate_entry()."
    )


def _synthesize_audit_diagnosis(
    *,
    overall_status: str,
    profit_status: str,
    loss_status: str,
    total_session_fills: int,
    lookback_fills: int,
    screen_snap: dict[str, Any],
    freshness_logs: dict[str, Any],
    meta_age: float | None,
    signals_age: float | None,
    missed_findings: list[dict[str, Any]],
    hedge_regime: str | None,
    tape_trend: str | None,
    vix_last: float | None,
    market_open: bool,
    market_reason: str,
) -> dict[str, Any]:
    """
    Single narrative that orders root causes for operators (heuristic, not causal proof).
    """
    drivers: list[dict[str, Any]] = []
    core = _core_jobs_log_freshness(freshness_logs or {})
    sn = (freshness_logs or {}).get("sniper.log") or {}
    sa = sn.get("age_hours")
    core_stale = bool(core.get("stale_gt_72h"))
    sniper_stale = bool(sn.get("exists") and sa is not None and float(sa) > 48)
    automation_stale = core_stale or sniper_stale

    if total_session_fills == 0 and lookback_fills >= 8:
        fill_detail = "Session has zero realized fills but ledger lookback shows prior activity."
        if not market_open:
            fill_detail += f" Market is currently closed ({market_reason}); verify again in next open window before treating as throughput incident."
        else:
            fill_detail += " Likely scheduler gap today or exits not hitting ledger yet."
        drivers.append(
            {
                "code": "session_throughput_gap_with_history",
                "weight": "medium" if not market_open else "high",
                "detail": fill_detail,
            }
        )

    if automation_stale and total_session_fills == 0 and market_open:
        if core_stale and sniper_stale:
            sched_detail = (
                "Core job logs (best of orchestrator/screener/monitor/fortress) and sniper.log look stale — "
                "cron may be down, TZ wrong, or jobs crashing before write."
            )
        elif core_stale:
            sched_detail = (
                "Core job logs (best of orchestrator/screener/monitor/fortress) look very old — "
                "screen/monitor/fortress schedule may be idle; confirm WorkingDirectory and log paths."
            )
        else:
            sched_detail = (
                "sniper.log is stale but other core logs look fresher — intraday sniper schedule may be broken "
                "(cron line, market-hours window, or snipe process errors); screen/monitor may still be OK."
            )
        drivers.append(
            {
                "code": "scheduler_or_log_staleness",
                "weight": "high",
                "detail": sched_detail,
            }
        )

    cf = int(screen_snap.get("candidates_found") or 0)
    eb = int(screen_snap.get("entry_buy_count") or 0)
    es = int(screen_snap.get("entry_skip_count") or 0)
    if cf > 0 and eb == 0 and es > 0:
        drivers.append(
            {
                "code": "entry_gate_all_skip",
                "weight": "high" if not automation_stale else "medium",
                "detail": f"Latest screen: {cf} candidate(s), 0 BUY, {es} SKIP — logic/timing/VIX likely blocking every name.",
            }
        )

    r = str(hedge_regime or "").upper()
    if "RISK_OFF" in r and eb == 0 and cf > 0:
        drivers.append(
            {
                "code": "regime_defensive_alignment",
                "weight": "medium",
                "detail": "Fortress RISK_OFF with zero BUYs can be intentional — separate from broken automation before loosening filters.",
            }
        )

    if vix_last is not None and float(vix_last) >= 22 and profit_status == "critical":
        drivers.append(
            {
                "code": "elevated_vol_throttle",
                "weight": "medium",
                "detail": f"VIX ~{vix_last} with weak throughput objective — spreads and discretionary skips often rise together.",
            }
        )

    if signals_age is not None and float(signals_age) > 36 and meta_age is not None and float(meta_age) > 36:
        drivers.append(
            {
                "code": "telemetry_stale",
                "weight": "medium",
                "detail": "Both screening meta and daily_signals timestamp look old — audits may describe an outdated funnel.",
            }
        )

    for f in missed_findings:
        if f.get("type") == "hitl_backlog":
            drivers.append(
                {
                    "code": "hitl_backlog",
                    "weight": "high",
                    "detail": str(f.get("text") or "Pending execution queue has approved trades."),
                }
            )
            break

    headline = (drivers[0]["detail"][:200] + ("…" if len(drivers[0]["detail"]) > 200 else "")) if drivers else "No single dominant driver; review objectives independently."

    parts: list[str] = []
    if automation_stale:
        parts.append(
            "Treat log staleness as an operations incident first: confirm systemd/cron, repo path, and log file targets."
        )
    if cf > 0 and eb == 0 and es > 0:
        parts.append("Inspect top_entry_skip_reasons in the newest daily_signals file before changing risk limits.")
    if "RISK_OFF" in r and eb == 0:
        parts.append("In RISK_OFF, zero equity BUYs may match policy; validate against fortress targets before chasing throughput.")
    if loss_status == "ok" and profit_status == "critical":
        parts.append("Loss objective is OK while profit throughput is critical — focus on entries/execution, not stop tightening.")
    if not market_open:
        parts.append("Market is currently closed; prioritize freshness checks and rerun throughput evaluation during next RTH window.")

    readiness = "critical" if overall_status == "critical" else ("degraded" if profit_status == "critical" or loss_status != "ok" else "nominal")

    return {
        "headline": headline,
        "primary_drivers": drivers,
        "narrative": " ".join(parts) if parts else "Review primary_drivers for ranked context.",
        "readiness": readiness,
        "tape_trend": tape_trend,
    }


def _actionable_bot_changes(
    *,
    diagnosis: dict[str, Any],
    screen_snap: dict[str, Any],
    params_snap: dict[str, Any],
    gate_rollup: dict[str, Any],
    execution_mode: str | None,
    eff_pol: dict[str, Any],
    market_open: bool,
) -> list[dict[str, Any]]:
    """
    Concrete, file/env-level suggestions (operator must validate; not auto-applied).
    """
    items: list[dict[str, Any]] = []
    codes = {d.get("code") for d in (diagnosis.get("primary_drivers") or [])}

    if "scheduler_or_log_staleness" in codes or ("session_throughput_gap_with_history" in codes and market_open):
        items.append(
            {
                "priority": 1,
                "severity": "high",
                "category": "automation",
                "title": "Fix scheduler + working directory for core jobs",
                "what_to_change": (
                    "Run `orchestrator.py screen` weekdays after open; run intraday sniper/spy jobs from the same repo root "
                    "that owns this data/ and logs/ tree."
                ),
                "where": "crontab or systemd unit · WorkingDirectory=/path/to/trading-bot · logs/sniper.log plus any of logs/screener.log, logs/monitor.log, logs/fortress.log, logs/orchestrator.log",
                "verify": "After one cycle, log mtimes < 24h and new lines appear; `data/daily_signals_*.json` timestamp fresh.",
                "caution": "Screens started from a different clone will not update this dashboard's data/.",
            }
        )

    top_sk = screen_snap.get("top_entry_skip_reasons") or []
    if top_sk and isinstance(top_sk[0], dict):
        r0 = str(top_sk[0].get("reason") or "")
        items.append(
            {
                "priority": 2,
                "severity": "medium",
                "category": "entry_logic",
                "title": "Adjust entry stack for dominant skip reason",
                "what_to_change": _map_skip_reason_to_entry_change(r0),
                "where": "agents/entry_agent.py · data/current_params.json · agents/screener_agent.py (tiers)",
                "verify": "Paper run: same candidate set yields BUY_count > 0 or documented intentional SKIP.",
                "caution": "Change one lever at a time; log before/after in decisions_log.",
            }
        )

    rollup_top = (gate_rollup.get("top_skip_reasons_rollup") or [])
    if rollup_top and isinstance(rollup_top[0], dict) and int(rollup_top[0].get("count") or 0) >= 8:
        rr = str(rollup_top[0].get("reason") or "")
        if not (top_sk and isinstance(top_sk[0], dict) and rr == str(top_sk[0].get("reason") or "")):
            items.append(
                {
                    "priority": 3,
                    "severity": "low",
                    "category": "entry_logic",
                    "title": "Persistent multi-day skip theme",
                    "what_to_change": _map_skip_reason_to_entry_change(rr),
                    "where": "Same as entry_logic; use rollup across daily_signals_* for confirmation.",
                    "verify": "After change, rollup count for that reason drops over next 3 screens.",
                    "caution": "",
                }
            )

    if params_snap.get("loaded"):
        items.append(
            {
                "priority": 4,
                "severity": "low",
                "category": "parameters",
                "title": "Record active auto-tuned parameters",
                "what_to_change": (
                    f"Current rsi_threshold={params_snap.get('rsi_threshold')}, "
                    f"stop_loss_pct={params_snap.get('stop_loss_pct')}, "
                    f"take_profit_pct={params_snap.get('take_profit_pct')} "
                    f"(last_updated={params_snap.get('last_updated')}). Compare to skip reasons above."
                ),
                "where": str(params_snap.get("path") or "data/current_params.json"),
                "verify": "agents/performance_analyzer tuning logs / parameter_history if enabled.",
                "caution": "Do not loosen stops under active loss streak without risk review.",
            }
        )

    if str(execution_mode or "").lower().replace("-", "_") in ("human_in_loop", "humaninloop"):
        items.append(
            {
                "priority": 2,
                "severity": "medium",
                "category": "execution",
                "title": "Human-in-the-loop: drain pending queue",
                "what_to_change": "Approved trades are not sent until operator runs execute_pending or UI flow.",
                "where": "python3 orchestrator.py execute_pending · data/pending_execution_queue.json",
                "verify": "pending_trade_count → 0 and broker shows new orders (paper).",
                "caution": "",
            }
        )

    if eff_pol.get("profile_drift_hint"):
        items.append(
            {
                "priority": 5,
                "severity": "low",
                "category": "policy",
                "title": "Align env profile with screening meta",
                "what_to_change": eff_pol["profile_drift_hint"],
                "where": "systemd Environment= · .env · export TRADING_POLICY_PROFILE=...",
                "verify": "last_screening_meta.json policy_profile matches runtime intent.",
                "caution": "",
            }
        )

    items.append(
        {
            "priority": 6,
            "severity": "low",
            "category": "research",
            "title": "Refresh illustrative research artifacts",
            "what_to_change": "Regenerate walk-forward + daily backtest snapshot so audit research block matches current code.",
            "where": "python3 agents/walk_forward_validator.py · GET /api/backtest?refresh=1 (dashboard) or run_daily_momentum_backtest",
            "verify": "data/walk_forward_report.json and data/backtest_snapshot.json mtimes fresh.",
            "caution": "Backtest is exploratory, not live performance.",
        }
    )

    items.sort(key=lambda x: int(x.get("priority") or 99))
    return items[:12]


def _flow_research_recommendations(
    *,
    rollup: dict[str, Any],
    freshness_logs: dict[str, Any],
    meta_mtime_age: float | None,
    signals_age: float | None,
    exit_sum: dict[str, Any],
    research: dict[str, Any],
    pending_age: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extra heuristics for flow, exits, and research artifacts."""
    recs: list[dict[str, Any]] = []
    tops = rollup.get("top_skip_reasons_rollup") or []
    if tops and isinstance(tops[0], dict) and int(tops[0].get("count") or 0) >= 12:
        r = str(tops[0].get("reason") or "")[:120]
        recs.append(
            {
                "severity": "low",
                "title": "Recurring entry skip pattern (multi-day rollup)",
                "body": f"Across recent daily_signals files, skips pile up for: {r}",
                "action": "operator: adjust entry evaluation / prefilter for that reason; compare shadow fills.",
            }
        )

    sn = (freshness_logs or {}).get("sniper.log") or {}
    core = _core_jobs_log_freshness(freshness_logs or {})
    sn_stale = bool(sn.get("exists") and (sn.get("age_hours") or 0) > 48)
    core_stale = bool(core.get("stale_gt_72h"))
    if sn_stale and core_stale:
        bn = core.get("best_name") or "core job logs"
        ba = core.get("best_age_hours")
        recs.append(
            {
                "severity": "high",
                "title": "Multiple core logs stale (automation incident)",
                "body": (
                    f"sniper.log ~{sn.get('age_hours')}h; freshest core job log is {bn} ~{ba}h "
                    "(orchestrator/screener/monitor/fortress) — treat as one ops problem (cron, cwd, or TZ)."
                ),
                "action": "operator: fix systemd/cron WorkingDirectory to repo root; confirm jobs write to this logs/ tree.",
            }
        )
    else:
        if sn_stale:
            recs.append(
                {
                    "severity": "medium",
                    "title": "Sniper log looks stale",
                    "body": f"sniper.log mtime ~{sn.get('age_hours')}h — intraday agent may not be running on schedule.",
                    "action": "operator: check crontab/systemd for intraday_sniper and host clock.",
                }
            )
        if core_stale:
            bn = core.get("best_name") or "none"
            ba = core.get("best_age_hours")
            recs.append(
                {
                    "severity": "low",
                    "title": "Core job logs quiet",
                    "body": (
                        f"Best of orchestrator/screener/monitor/fortress logs: {bn} ~{ba}h — "
                        "daily screen / monitor / fortress cadence may be idle."
                    ),
                    "action": "operator: verify cron lines for screen, monitor, fortress; check logs/screener.log and logs/monitor.log.",
                }
            )

    if meta_mtime_age is not None and meta_mtime_age > 36:
        recs.append(
            {
                "severity": "low",
                "title": "Screening meta file aging",
                "body": f"last_screening_meta.json is ~{meta_mtime_age}h old vs now.",
                "action": "operator: run screener / orchestrator screen so telemetry stays fresh.",
            }
        )

    if signals_age is not None and signals_age > 48:
        recs.append(
            {
                "severity": "medium",
                "title": "Latest daily_signals timestamp is old",
                "body": f"Newest daily_signals run timestamp is ~{signals_age}h behind audit clock.",
                "action": "operator: run daily screening; stale signals distort funnel audit.",
            }
        )

    if int(exit_sum.get("exit_failures_sum") or 0) > 0:
        recs.append(
            {
                "severity": "medium",
                "title": "Exit monitor reported broker failures",
                "body": f"exit_signals artifact shows {exit_sum.get('exit_failures_sum')} failure(s) in recent window.",
                "action": "operator: review Alpaca rejects and exit_monitor logs; fix order sizing or market hours.",
            }
        )

    wf = (research.get("walk_forward_summary") or {}) if isinstance(research, dict) else {}
    if wf.get("stable") is False:
        recs.append(
            {
                "severity": "low",
                "title": "Walk-forward stability flag is negative",
                "body": (wf.get("reason") or "See data/walk_forward_report.json")[:300],
                "action": "operator: python3 agents/walk_forward_validator.py — treat strategy promotion cautiously.",
            }
        )

    oa = pending_age.get("oldest_pending_batch_age_hours")
    if oa is not None and oa > 24 and int(pending_age.get("pending_trade_count") or 0) > 0:
        recs.append(
            {
                "severity": "medium",
                "title": "Aging HITL pending queue",
                "body": f"Oldest pending batch ~{oa}h old — approved risk not reaching broker.",
                "action": "operator: run orchestrator execute_pending or clear stale batches after review.",
            }
        )

    return recs[:6]


def _load_hedging_context(
    data_dir: Path,
    *,
    max_age_hours: float = 36.0,
) -> dict[str, Any]:
    """
    Latest fortress_report_*.json plus optional hedging_recommendations.json (read-only).
    """
    ctx: dict[str, Any] = {
        "fortress_report_path": None,
        "fortress_report_age_hours": None,
        "fortress_report_fresh": False,
        "market_conditions": {},
        "strategy_headlines": [],
        "hedging_recommendations_loaded": False,
        "notes": [],
    }
    pattern = str(data_dir / "fortress_report_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        ctx["notes"].append("no_fortress_report_json")
        return ctx
    path = Path(files[0])
    ctx["fortress_report_path"] = str(path)
    try:
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        ctx["fortress_report_age_hours"] = round(age_h, 2)
        ctx["fortress_report_fresh"] = age_h <= max_age_hours
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            mc = raw.get("market_conditions") or {}
            ctx["market_conditions"] = mc if isinstance(mc, dict) else {}
            strat = raw.get("strategies") or {}
            ctx["strategy_headlines"] = _fortress_strategy_headlines(strat if isinstance(strat, dict) else {})
            ctx["fortress_note"] = raw.get("note")
    except Exception as e:
        ctx["notes"].append(f"fortress_read_error:{type(e).__name__}:{e}")

    hr_path = data_dir / "hedging_recommendations.json"
    if hr_path.exists():
        try:
            rec = json.loads(hr_path.read_text(encoding="utf-8"))
            ctx["hedging_recommendations"] = rec if isinstance(rec, dict) else {"raw": rec}
            ctx["hedging_recommendations_loaded"] = True
        except Exception as e:
            ctx["notes"].append(f"hedging_recommendations_error:{type(e).__name__}:{e}")

    return ctx


def _fortress_strategy_headlines(strategies: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, s in strategies.items():
        if not isinstance(s, dict):
            continue
        if name == "bonds":
            tgt = s.get("target")
            if tgt is not None:
                out.append({"strategy": name, "summary": f"target={tgt}", "reason": (s.get("reason") or "")[:160]})
            else:
                out.append({"strategy": name, "summary": "no_target", "reason": (s.get("reason") or "")[:160]})
            continue
        action = s.get("action")
        if action is not None:
            out.append(
                {
                    "strategy": name,
                    "summary": str(action),
                    "reason": (s.get("reason") or s.get("opportunity") or "")[:160],
                }
            )
        else:
            out.append({"strategy": name, "summary": "see_report", "reason": ""})
    return out[:14]


def _hedging_contrast_analysis(
    *,
    pnl_session: float,
    loss_status: str,
    profit_status: str,
    hedge_ctx: dict[str, Any],
) -> dict[str, Any]:
    """
    Compare session bot performance with latest hedge / fortress opportunities.
    """
    regime = hedge_ctx.get("market_conditions", {}).get("regime") if isinstance(hedge_ctx.get("market_conditions"), dict) else None
    vix = hedge_ctx.get("market_conditions", {}).get("vix") if isinstance(hedge_ctx.get("market_conditions"), dict) else None
    fresh = bool(hedge_ctx.get("fortress_report_fresh"))
    headlines = hedge_ctx.get("strategy_headlines") or []

    findings: list[dict[str, Any]] = []
    aligned: bool | None = None

    if not hedge_ctx.get("fortress_report_path"):
        findings.append(
            {
                "type": "context",
                "text": "No fortress_report_*.json found — cannot contrast bot P&L with hedge opportunities.",
            }
        )
        summary = "Missing fortress hedge report."
        return {"summary": summary, "findings": findings, "aligned": None, "regime": regime, "vix": vix}

    if not fresh:
        findings.append(
            {
                "type": "stale",
                "text": f"Fortress report is stale (~{hedge_ctx.get('fortress_report_age_hours')}h old). Refresh (orchestrator fortress / hedge cycle) before trusting hedge contrast.",
            }
        )

    r = str(regime or "").strip().upper()
    summary_parts: list[str] = []

    if loss_status in ("warn", "critical") and pnl_session < 0:
        aligned = False
        if "RISK_OFF" in r:
            findings.append(
                {
                    "type": "align",
                    "text": "Session realized P&L is negative while fortress regime is RISK_OFF — defensive tilt is expected; check whether directional bots are oversized vs bond/commodity/FX hedge targets.",
                }
            )
            summary_parts.append("Losses in RISK_OFF: reconcile equity bots with defensive hedge targets.")
        elif r in ("RISK_ON", "NEUTRAL", ""):
            findings.append(
                {
                    "type": "tension",
                    "text": f"Session losses with regime {regime or 'unknown'}: consider running a fresh fortress cycle and tightening gates if hedge stack still shows risk-on lean.",
                }
            )
            summary_parts.append("Losses vs regime: validate hedge run and entry sizing.")
    elif pnl_session >= 0 and loss_status == "ok":
        aligned = True
        findings.append(
            {
                "type": "align",
                "text": "Session realized P&L supports the near-zero-loss objective; still compare open hedge legs if regime flipped since last fortress run.",
            }
        )
        summary_parts.append("P&L healthy vs session window; confirm hedges match current regime.")

    if profit_status in ("warn", "critical") and pnl_session <= 0 and r == "RISK_ON":
        findings.append(
            {
                "type": "opportunity",
                "text": "Low session throughput or weak outcomes while regime is RISK_ON — review screening vs execution; hedges may be idle while equity opportunity set should be wider.",
            }
        )
        summary_parts.append("Throughput vs RISK_ON: check screen → execute path.")

    if hedge_ctx.get("hedging_recommendations_loaded"):
        findings.append(
            {
                "type": "context",
                "text": "hedging_recommendations.json present — cross-check those notes with worst strategies below.",
            }
        )

    summary = " ".join(summary_parts) if summary_parts else "Cross-check session bot performance with fortress hedge opportunities."
    return {
        "summary": summary,
        "findings": findings,
        "aligned": aligned,
        "regime": regime,
        "vix": vix,
        "headlines": headlines,
    }


def _extract_strategy_key(rec: dict[str, Any]) -> str:
    """
    Attempt to label a ledger row by its originating strategy/source.
    """
    for k in ("strategy_id", "strategy", "source", "type"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Fallbacks for older/variant rows.
    ticker = rec.get("ticker") or rec.get("symbol") or "UnknownTicker"
    return f"UnknownStrategy({ticker})"


def _audit_objective_loss_health(
    *,
    pnl_today: float,
    wins_today: int,
    losses_today: int,
    total_today: int,
    consecutive_losses: int | None,
    session_label: str = "session (since 3 AM ET)",
) -> tuple[str, list[dict[str, Any]]]:
    """
    Returns (status, findings[]).
    """
    findings: list[dict[str, Any]] = []

    loss_rate = (losses_today / total_today * 100.0) if total_today else None
    if loss_rate is not None:
        findings.append(
            {
                "metric": "loss_rate_session_pct",
                "value": round(loss_rate, 2),
                "target": "<= 40% (heuristic)",
                "window": session_label,
            }
        )

    findings.append(
        {
            "metric": "realized_pnl_session_et",
            "value": round(pnl_today, 2),
            "target": ">= -X (heuristic)",
            "window": session_label,
        }
    )

    if consecutive_losses is not None:
        findings.append(
            {
                "metric": "risk_guardian_consecutive_losses",
                "value": int(consecutive_losses),
                "target": "<= 1 for near-zero-loss objective",
            }
        )

    # Heuristic status:
    # - "ok" if pnl_today >= 0 and losses <= wins (or no trades)
    # - "warn" if pnl_today < 0 but not catastrophic
    # - "critical" if pnl_today is negative AND loss rate high OR circuit breaker-like streak.
    status = "warn"
    if total_today == 0:
        status = "ok"
        findings.append({"metric": "trade_count_session", "value": 0, "target": "ok", "window": session_label})
    else:
        if pnl_today >= 0 and (losses_today <= wins_today):
            status = "ok"
        else:
            high_loss_rate = (loss_rate is not None) and (loss_rate >= 60)
            bad_streak = (consecutive_losses is not None) and (int(consecutive_losses) >= 3)
            if high_loss_rate or bad_streak:
                status = "critical"

    return status, findings


def _audit_objective_profit_opportunities(
    *,
    total_today: int,
    wins_today: int,
    total_lb: int,
    wins_lb: int,
    session_label: str = "session (since 3 AM ET)",
) -> tuple[str, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    win_rate_today = (wins_today / total_today * 100.0) if total_today else None
    win_rate_lb = (wins_lb / total_lb * 100.0) if total_lb else None

    findings.append(
        {"metric": "executed_trades_session", "value": total_today, "target": ">= 1", "window": session_label}
    )
    if win_rate_today is not None:
        findings.append(
            {
                "metric": "win_rate_session_pct",
                "value": round(win_rate_today, 2),
                "target": ">= 45%",
                "window": session_label,
            }
        )
    if win_rate_lb is not None:
        findings.append(
            {
                "metric": "win_rate_lookback_pct",
                "value": round(win_rate_lb, 2),
                "target": ">= 45% (heuristic)",
            }
        )

    status = "warn"
    if total_today == 0 and total_lb == 0:
        status = "warn"
        findings.append({"metric": "throughput", "value": "no ledger fills", "target": "needs data"})
    else:
        if win_rate_today is not None and win_rate_today >= 50 and total_today >= 1:
            status = "ok"
        elif total_today >= 1:
            status = "warn"
        else:
            status = "critical"
            findings.append(
                {"metric": "throughput", "value": "0 fills in session window", "target": ">= 1", "window": session_label}
            )

    return status, findings


def audit_bot_performance(
    *,
    data_dir: Path | None = None,
    logs_dir: Path | None = None,
    lookback_days: int = 30,
    audit_days: int = 1,
    now_utc: datetime | None = None,
    include_market: bool | None = None,
) -> dict[str, Any]:
    """
    Read-only audit. Returns a JSON-serializable report.

    Session metrics (fills, P&L, win rate for objectives) use a window starting at
    03:00 America/New_York through "now" (before 3 AM local, the window begins the
    previous calendar day at 3 AM). Calendar `lookback_days` still scopes the longer
    ledger win-rate context. Contrasts session bot outcomes with latest
    fortress_report_*.json / hedging_recommendations.json when present.

    When `include_market` is True (default from env BOT_AUDIT_FETCH_MARKET), pulls
    delayed benchmark/VIX via yfinance for tape vs bot analysis (no orders).

    Uses latest ``daily_signals_*.json``, ``pending_execution_queue.json``, and
    ``decisions_log.jsonl`` (session window) for funnel / missed-opportunity heuristics.

    Also rolls up recent screens (gate reasons), log/Screening freshness, exit_signals,
    ``walk_forward_report.json`` / ``backtest_snapshot.json``, and policy/cost hints.
    """
    data_dir = data_dir or DEFAULT_DATA_DIR
    logs_dir = logs_dir or DEFAULT_LOGS_DIR
    now_utc = now_utc or datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    market_open = (now_et.weekday() < 5) and (dt_time(9, 30) <= now_et.time() <= dt_time(16, 0))
    if now_et.weekday() >= 5:
        market_reason = "weekend"
    elif now_et.time() < dt_time(9, 30):
        market_reason = "pre_market"
    elif now_et.time() > dt_time(16, 0):
        market_reason = "after_hours"
    else:
        market_reason = "rth_open"

    # Calendar day of "now" in ET (reference). Session stats use 3 AM ET anchor, not midnight.
    day0 = now_et.date()
    day_start_lb = (now_utc - timedelta(days=lookback_days)).date()
    session_start_et = _et_audit_window_start(now_et)
    session_label = "since 3:00 AM America/New_York"

    ledger_path = data_dir / "pnl_ledger.jsonl"
    risk_state_path = data_dir / "risk_guardian_state.json"
    operational_runs_path = data_dir / "operational_runs.jsonl"
    last_screening_meta_path = data_dir / "last_screening_meta.json"

    # Risk guardian consecutive losses (if persisted).
    consecutive_losses: int | None = None
    if risk_state_path.exists():
        try:
            st = json.loads(risk_state_path.read_text(encoding="utf-8"))
            consecutive_losses = int(st.get("consecutive_losses")) if st.get("consecutive_losses") is not None else None
        except Exception:
            consecutive_losses = None

    # Ledger stats.
    pnl_today = 0.0
    wins_today = 0
    losses_today = 0
    total_today = 0

    pnl_lb = 0.0
    wins_lb = 0
    losses_lb = 0
    total_lb = 0

    by_strategy: dict[str, dict[str, Any]] = {}
    recent_rows: list[dict[str, Any]] = []

    for rec in _iter_jsonl(ledger_path):
        if not isinstance(rec, dict):
            continue
        pnl = _safe_float(rec.get("pnl"))
        if pnl is None:
            continue
        ts = _parse_timestamp_local_iso(rec.get("timestamp"))
        if ts is None:
            continue
        if ts > now_et:
            continue
        rec_day = ts.date()
        in_session = ts >= session_start_et

        if in_session:
            total_today += 1
            pnl_today += pnl
            if pnl > 0:
                wins_today += 1
            elif pnl < 0:
                losses_today += 1

        if rec_day >= day_start_lb:
            total_lb += 1
            pnl_lb += pnl
            if pnl > 0:
                wins_lb += 1
            elif pnl < 0:
                losses_lb += 1

        if in_session:
            sk = _extract_strategy_key(rec)
            st = by_strategy.setdefault(sk, {"strategy": sk, "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
            st["trades"] += 1
            st["pnl"] += pnl
            if pnl > 0:
                st["wins"] += 1
            elif pnl < 0:
                st["losses"] += 1

            recent_rows.append(rec)
            if len(recent_rows) > 50:
                recent_rows.pop(0)

    # Process stats (registry run success).
    process = {"today_screening_runs": [], "recent_screening_runs": [], "notes": []}
    if operational_runs_path.exists():
        try:
            # Only read a limited tail for speed.
            ops_rows = list(_iter_jsonl(operational_runs_path))
            # Reduce scan: keep last 400 ops.
            ops_rows = ops_rows[-400:]
            # Group by run_id in a lightweight way.
            by_run: dict[str, dict[str, Any]] = {}
            for ev in ops_rows:
                if not isinstance(ev, dict):
                    continue
                et = ev.get("event_type")
                if et not in (
                    "screening_run_started",
                    "screening_run_completed",
                    "screening_run_failed",
                ):
                    continue
                payload = ev.get("payload") or {}
                rid = payload.get("run_id")
                if not rid:
                    continue
                row = by_run.setdefault(rid, {"run_id": rid, "event_type": et, "payload": {}})
                # terminal rows overwrite payload keys.
                if ev.get("event_type") in ("screening_run_completed", "screening_run_failed"):
                    row["terminal"] = ev.get("event_type")
                    row["payload"] = payload
                    row["timestamp"] = ev.get("timestamp")
                else:
                    row["payload"] = payload
            # Build list and filter by ET day.
            all_runs = []
            for rid, row in by_run.items():
                ts = _parse_timestamp_local_iso(row.get("timestamp")) if row.get("timestamp") else None
                if ts:
                    all_runs.append({**row, "et_date": ts.date().isoformat()})
                else:
                    all_runs.append({**row, "et_date": None})
            all_runs_sorted = sorted(all_runs, key=lambda x: x.get("timestamp") or "", reverse=True)
            process["recent_screening_runs"] = all_runs_sorted[:8]
            session_runs = []
            for r in all_runs_sorted:
                rts = _parse_timestamp_local_iso(r.get("timestamp"))
                if rts and rts >= session_start_et:
                    session_runs.append(r)
            process["session_screening_runs"] = session_runs[:6]
            process["today_screening_runs"] = process["session_screening_runs"]
        except Exception as e:
            process["notes"].append(f"operational_runs parse error: {type(e).__name__}:{e}")

    last_meta = {}
    if last_screening_meta_path.exists():
        try:
            last_meta = json.loads(last_screening_meta_path.read_text(encoding="utf-8"))
        except Exception:
            last_meta = {}

    latest_signals, latest_signals_path = _load_latest_daily_signals(data_dir)
    screen_snap = _summarize_daily_signals(latest_signals, latest_signals_path)
    pending_snap = _summarize_pending_queue(data_dir)
    pending_snap.update(_pending_age_detail(data_dir, now_utc))
    dec_snap = _decisions_log_session_snapshot(
        data_dir / "decisions_log.jsonl",
        session_start_et,
        now_et,
    )

    gate_rollup = _rollup_gate_attribution(data_dir)
    exit_monitor = _exit_signals_summary(data_dir)
    research_bt = _research_backtest_block(data_dir)
    freshness_logs = _log_staleness(
        logs_dir,
        (
            "orchestrator.log",
            "screener.log",
            "monitor.log",
            "fortress.log",
            "sniper.log",
            "spy_swing.log",
        ),
        now_utc,
    )
    meta_mtime_age = _file_mtime_age_hours(last_screening_meta_path, now_utc)
    signals_ts_age = _signal_timestamp_age_hours(screen_snap.get("timestamp"), now_utc)
    eff_pol = _efficiency_and_policy_snapshot(
        latest_signals if isinstance(latest_signals, dict) else None,
        last_meta if isinstance(last_meta, dict) else {},
    )
    params_snap = _read_current_params_snapshot(data_dir)

    # Objective evaluation (session = since 3 AM ET).
    loss_status, loss_findings = _audit_objective_loss_health(
        pnl_today=pnl_today,
        wins_today=wins_today,
        losses_today=losses_today,
        total_today=total_today,
        consecutive_losses=consecutive_losses,
        session_label=session_label,
    )
    profit_status, profit_findings = _audit_objective_profit_opportunities(
        total_today=total_today,
        wins_today=wins_today,
        total_lb=total_lb,
        wins_lb=wins_lb,
        session_label=session_label,
    )

    overall_status = "warn"
    if loss_status == "critical" or (profit_status == "critical" and market_open):
        overall_status = "critical"
    elif loss_status == "ok" and profit_status == "ok":
        overall_status = "ok"

    strategies_sorted = sorted(by_strategy.values(), key=lambda x: x.get("pnl", 0.0))
    worst = strategies_sorted[:4]
    best = list(reversed(strategies_sorted))[:4]

    if include_market is None:
        include_market = os.getenv("BOT_AUDIT_FETCH_MARKET", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

    market_ctx: dict[str, Any]
    if include_market:
        market_ctx = fetch_market_performance_context()
    else:
        market_ctx = {"ok": False, "disabled": True, "reason": "include_market_false"}

    mvb = _market_vs_bot_analysis(
        market=market_ctx,
        pnl_session=pnl_today,
        loss_status=loss_status,
        profit_status=profit_status,
        total_session_trades=total_today,
    )

    hedge_ctx = _load_hedging_context(data_dir)
    contrast = _hedging_contrast_analysis(
        pnl_session=pnl_today,
        loss_status=loss_status,
        profit_status=profit_status,
        hedge_ctx=hedge_ctx,
    )

    hedge_payload: dict[str, Any] = {
        "fortress_report_path": hedge_ctx.get("fortress_report_path"),
        "fortress_report_age_hours": hedge_ctx.get("fortress_report_age_hours"),
        "fortress_report_fresh": hedge_ctx.get("fortress_report_fresh"),
        "regime": (hedge_ctx.get("market_conditions") or {}).get("regime"),
        "vix": (hedge_ctx.get("market_conditions") or {}).get("vix"),
        "strategy_headlines": hedge_ctx.get("strategy_headlines") or [],
        "hedging_recommendations_loaded": bool(hedge_ctx.get("hedging_recommendations_loaded")),
        "notes": hedge_ctx.get("notes") or [],
    }
    if hedge_ctx.get("fortress_note"):
        hedge_payload["fortress_note"] = hedge_ctx.get("fortress_note")

    contrast_out = {
        "summary": contrast.get("summary"),
        "findings": contrast.get("findings") or [],
        "aligned": contrast.get("aligned"),
        "regime": contrast.get("regime"),
        "vix": contrast.get("vix"),
    }

    vix_for_syn: float | None = None
    try:
        if market_ctx.get("vix_last") is not None:
            vix_for_syn = float(market_ctx["vix_last"])
    except (TypeError, ValueError):
        vix_for_syn = None

    missed = _missed_opportunity_analysis(
        screen=screen_snap,
        pending=pending_snap,
        decisions=dec_snap,
        session_ledger_trades=total_today,
    )
    alts = _alternative_strategy_suggestions(
        worst=worst,
        best=best,
        screen=screen_snap,
        last_meta=last_meta if isinstance(last_meta, dict) else {},
        loss_status=loss_status,
        tape_trend=mvb.get("tape_trend"),
        hedge_regime=hedge_payload.get("regime"),
        consecutive_losses=consecutive_losses,
    )

    diagnosis = _synthesize_audit_diagnosis(
        overall_status=overall_status,
        profit_status=profit_status,
        loss_status=loss_status,
        total_session_fills=total_today,
        lookback_fills=total_lb,
        screen_snap=screen_snap,
        freshness_logs=freshness_logs,
        meta_age=meta_mtime_age,
        signals_age=signals_ts_age,
        missed_findings=missed.get("findings") or [],
        hedge_regime=hedge_payload.get("regime"),
        tape_trend=mvb.get("tape_trend"),
        vix_last=vix_for_syn,
        market_open=market_open,
        market_reason=market_reason,
    )
    actionable = _actionable_bot_changes(
        diagnosis=diagnosis,
        screen_snap=screen_snap,
        params_snap=params_snap,
        gate_rollup=gate_rollup,
        execution_mode=screen_snap.get("execution_mode"),
        eff_pol=eff_pol,
        market_open=market_open,
    )

    # Recommendations: deterministic heuristics.
    recommendations: list[dict[str, Any]] = []
    hl = (diagnosis.get("headline") or "Review primary_drivers")[:120]
    diag_sev = "high" if diagnosis.get("readiness") == "critical" else "medium"
    recommendations.append(
        {
            "severity": diag_sev,
            "title": f"Unified diagnosis — {hl}",
            "body": (diagnosis.get("narrative") or "")[:1100],
            "action": "operator: use audit_synthesis.primary_drivers (ranked) and actionable_changes[] for concrete file/env edits; validate on paper before live.",
        }
    )
    for ac in actionable[:6]:
        recommendations.append(
            {
                "severity": str(ac.get("severity") or "low"),
                "title": f"Bot change · {ac.get('category', 'system')}: {(ac.get('title') or '')[:76]}",
                "body": ((ac.get("what_to_change") or "") + (f" Caution: {ac['caution']}" if ac.get("caution") else ""))[:900],
                "action": f"{ac.get('where', '')} | Verify: {ac.get('verify', '')}"[:650],
            }
        )

    hedge_body = (contrast.get("summary") or "").strip()
    for f in contrast.get("findings") or []:
        if f.get("type") in ("tension", "stale", "align", "opportunity"):
            t = str(f.get("text") or "").strip()
            if t and t not in hedge_body:
                hedge_body = (hedge_body + " " + t).strip() if hedge_body else t
    sev = "medium"
    if contrast.get("aligned") is not False and not any(
        f.get("type") in ("tension", "stale") for f in (contrast.get("findings") or [])
    ):
        sev = "low"
    recommendations.append(
        {
            "severity": sev,
            "title": "Hedge / fortress vs session bot performance",
            "body": hedge_body[:1200] if hedge_body else "Cross-check session bot P&L with fortress hedge opportunities.",
            "action": "operator: review latest data/fortress_report_*.json and data/hedging_recommendations.json; run `python3 orchestrator.py fortress` if the report is stale.",
        }
    )

    tape_body = (mvb.get("summary") or "").strip()
    for f in mvb.get("findings") or []:
        if f.get("type") in ("tension", "align", "opportunity", "context"):
            t = str(f.get("text") or "").strip()
            if t and t not in tape_body:
                tape_body = (tape_body + " " + t).strip() if tape_body else t
    tape_sev = "medium" if any(f.get("type") == "tension" for f in (mvb.get("findings") or [])) else "low"
    recommendations.append(
        {
            "severity": tape_sev,
            "title": "Market tape vs session bot",
            "body": tape_body[:1200] if tape_body else "No market context.",
            "action": "operator: optional env BOT_AUDIT_BENCHMARK=SPY (or IWM/QQQ); disable fetches with BOT_AUDIT_FETCH_MARKET=0 or API ?market=0.",
        }
    )

    miss_body = (missed.get("summary") or "").strip()
    miss_sev = "medium" if any(f.get("type") in ("hitl_backlog", "execution_gap", "broker_failures") for f in (missed.get("findings") or [])) else "low"
    recommendations.append(
        {
            "severity": miss_sev,
            "title": "Missed opportunities (funnel / backlog)",
            "body": miss_body[:1200] if miss_body else "No funnel backlog detected from latest artifacts.",
            "action": "operator: open latest data/daily_signals_*.json, pending_execution_queue.json, decisions_log.jsonl; clear HITL or fix gate reasons blocking fills.",
        }
    )
    for sug in (alts.get("suggestions") or [])[:4]:
        recommendations.append(
            {
                "severity": "low",
                "title": f"Alternative posture: {sug.get('title', 'idea')[:80]}",
                "body": (sug.get("rationale") or "")[:500],
                "action": (sug.get("action") or "")[:500],
            }
        )

    flow_recs = _flow_research_recommendations(
        rollup=gate_rollup,
        freshness_logs=freshness_logs,
        meta_mtime_age=meta_mtime_age,
        signals_age=signals_ts_age,
        exit_sum=exit_monitor,
        research=research_bt,
        pending_age={
            "oldest_pending_batch_age_hours": pending_snap.get("oldest_pending_batch_age_hours"),
            "pending_trade_count": pending_snap.get("pending_trade_count"),
        },
    )
    for fr in flow_recs:
        recommendations.append(fr)

    if overall_status in ("critical", "warn"):
        if total_today == 0:
            recommendations.append(
                {
                    "severity": (
                        "low"
                        if not market_open
                        else ("high" if overall_status == "critical" else "medium")
                    ),
                    "title": "No fills in session window — check opportunity→execution path",
                    "body": (
                        f"Ledger shows 0 realized P&L rows {session_label}. "
                        + (
                            f"Market is currently closed ({market_reason}); prioritize freshness checks now and re-evaluate after open."
                            if not market_open
                            else "Verify cron scheduling (screen/snipe/spy_swing), execution_mode, and that orders were not deferred or blocked by pre_trade_gate."
                        )
                    ),
                    "action": (
                        "operator: verify `crontab -l` + `logs/sniper.log` freshness now; rerun `python3 orchestrator.py screen` during next RTH window."
                        if not market_open
                        else "operator: run `python3 orchestrator.py screen` (then execute_pending if HITL) and/or check `crontab -l` + `logs/sniper.log` freshness."
                    ),
                }
            )
        if loss_status != "ok":
            recommendations.append(
                {
                    "severity": "high" if loss_status == "critical" else "medium",
                    "title": "Loss discipline degraded — tighten gates",
                    "body": f"Near-zero-loss objective looks unhealthy for the session {session_label}. Consider switching profile to capital_preservation, enforcing shadow-only for high-vol agents, and reviewing risk_guardian circuit breaker state.",
                    "action": "operator: set `TRADING_POLICY_PROFILE=capital_preservation` or activate operator halt if needed; review `data/risk_guardian_state.json`.",
                }
            )

    # Always include agent breakdown guidance.
    # Only recommend if we have data.
    if by_strategy:
        recommendations.append(
            {
                "severity": "low",
                "title": "Agent-level performance: focus worst offenders",
                "body": f"Worst: {[w['strategy'] + ' pnl=' + str(round(w['pnl'], 2)) for w in worst]} ; Best: {[b['strategy'] + ' pnl=' + str(round(b['pnl'], 2)) for b in best]}",
                "action": "operator: disable or shadow-only the worst-performing strategy via config/profile, then rerun paper for 1-2 sessions.",
            }
        )

    return {
        "timestamp": now_et.isoformat(),
        "objective_day_et": day0.isoformat(),
        "audit_window": {
            "anchor": "3am_america_new_york",
            "start_et": session_start_et.isoformat(),
            "end_et": now_et.isoformat(),
            "label": session_label,
            "market_open": market_open,
            "market_reason": market_reason,
        },
        "lookback_days": lookback_days,
        "audited": {
            "ledger_path": str(ledger_path),
            "ledger_rows_considered_lb": total_lb,
            "ledger_rows_today": total_today,
            "ledger_rows_session_et": total_today,
        },
        "objectives": {
            "profit_opportunities": {
                "status": profit_status,
                "findings": profit_findings,
            },
            "near_zero_losses": {
                "status": loss_status,
                "findings": loss_findings,
            },
            "market_backdrop": {
                "status": "ok" if market_ctx.get("ok") else "unavailable",
                "findings": _market_backdrop_findings(market_ctx),
            },
        },
        "hedging_context": hedge_payload,
        "hedging_contrast": contrast_out,
        "market_context": market_ctx,
        "market_vs_bot": {
            "summary": mvb.get("summary"),
            "tape_trend": mvb.get("tape_trend"),
            "findings": mvb.get("findings") or [],
        },
        "opportunity_pipeline": screen_snap,
        "pending_execution": pending_snap,
        "decisions_log_session": dec_snap,
        "missed_opportunities": {
            "summary": missed.get("summary"),
            "findings": missed.get("findings") or [],
            "inputs": missed.get("inputs") or {},
        },
        "alternative_strategies": {
            "summary": alts.get("summary"),
            "suggestions": alts.get("suggestions") or [],
        },
        "gate_attribution_rollup": gate_rollup,
        "freshness_sla": {
            "log_age_hours": freshness_logs,
            "core_jobs_log": _core_jobs_log_freshness(freshness_logs),
            "last_screening_meta_mtime_age_hours": meta_mtime_age,
            "latest_daily_signals_timestamp_age_hours": signals_ts_age,
        },
        "exit_monitoring": exit_monitor,
        "research_backtest": research_bt,
        "efficiency_and_policy": eff_pol,
        "current_params_snapshot": params_snap,
        "audit_synthesis": diagnosis,
        "actionable_changes": actionable,
        "process": {
            "today_screening_runs_count": len(process.get("session_screening_runs") or []),
            "session_screening_runs": process.get("session_screening_runs") or [],
            "recent_screening_runs": process.get("recent_screening_runs") or [],
            "last_screening_meta_loaded": bool(last_meta),
            "last_screening_meta_strict_mode": last_meta.get("strict_mode") if isinstance(last_meta, dict) else None,
        },
        "agent_performance": {
            "worst_strategies": [
                {"strategy": w["strategy"], "trades": w["trades"], "wins": w["wins"], "losses": w["losses"], "pnl": round(w["pnl"], 2)}
                for w in worst
            ],
            "best_strategies": [
                {"strategy": b["strategy"], "trades": b["trades"], "wins": b["wins"], "losses": b["losses"], "pnl": round(b["pnl"], 2)}
                for b in best
            ],
        },
        "recommendations": recommendations,
        "log_tails": {
            "orchestrator.log_tail": _read_text_tail(logs_dir / "orchestrator.log", 1600),
            "screener.log_tail": _read_text_tail(logs_dir / "screener.log", 1200),
            "monitor.log_tail": _read_text_tail(logs_dir / "monitor.log", 1200),
            "fortress.log_tail": _read_text_tail(logs_dir / "fortress.log", 1200),
            "sniper.log_tail": _read_text_tail(logs_dir / "sniper.log", 1200),
            "spy_swing.log_tail": _read_text_tail(logs_dir / "spy_swing.log", 1200),
        },
        "overall_status": overall_status,
    }

