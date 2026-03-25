"""
Bot Audit Agent

Purpose:
  Provide an operator-facing daily audit of the system against objectives:
    - keep losses near zero (risk discipline / realized PnL health)
    - maintain profit opportunities (signal-to-trade throughput + win rate)

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
    """
    data_dir = data_dir or DEFAULT_DATA_DIR
    logs_dir = logs_dir or DEFAULT_LOGS_DIR
    now_utc = now_utc or datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)

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
    if loss_status == "critical" or profit_status == "critical":
        overall_status = "critical"
    elif loss_status == "ok" and profit_status == "ok":
        overall_status = "ok"

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

    # Recommendations: deterministic heuristics.
    recommendations: list[dict[str, Any]] = []
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

    if overall_status in ("critical", "warn"):
        if total_today == 0:
            recommendations.append(
                {
                    "severity": "high" if overall_status == "critical" else "medium",
                    "title": "No fills in session window — check opportunity→execution path",
                    "body": f"Ledger shows 0 realized P&L rows {session_label}. Verify cron scheduling (screen/snipe/spy_swing), execution_mode, and that orders were not deferred or blocked by pre_trade_gate.",
                    "action": "operator: run `python3 orchestrator.py screen` (then execute_pending if HITL) and/or check `crontab -l` + `logs/sniper.log` freshness.",
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
    strategies_sorted = sorted(by_strategy.values(), key=lambda x: x.get("pnl", 0.0))
    worst = strategies_sorted[:4]
    best = list(reversed(strategies_sorted))[:4]

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
            "sniper.log_tail": _read_text_tail(logs_dir / "sniper.log", 1200),
            "spy_swing.log_tail": _read_text_tail(logs_dir / "spy_swing.log", 1200),
        },
        "overall_status": overall_status,
    }

