"""
Operator Morning Brief — dashboard-only contextual summary (informational, not advice).

Combines: US session calendar, light macro context, local stack checks, book-aware
hints from positions.json + yfinance (earnings window, recent move).
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# yfinance can be slow; macro + book rows are safe to cache briefly.
_MACRO_CACHE: dict[str, Any] = {"t": 0.0, "v": None}
_BOOK_CACHE: dict[str, Any] = {"t": 0.0, "key": (), "v": []}
_MACRO_TTL_SEC = 300.0
_BOOK_TTL_SEC = 600.0

_POLICY_ROTATION: list[dict[str, str]] = [
    {
        "title": "Recordkeeping & marketing",
        "body": "If client communications were drafted with AI, align with your firm’s marketing rule and archive policies — confirm with compliance.",
    },
    {
        "title": "Vendor diligence",
        "body": "Treat Fortress as self-hosted software under your vendor/tooling policy: you hold keys, discretion, and execution responsibility.",
    },
    {
        "title": "Model documentation",
        "body": "For systematic workflows, maintain written rationale for parameters, gates, and kill-switch use — consult your CCO on format.",
    },
    {
        "title": "Best execution / routing",
        "body": "Review broker routing and order types periodically; this platform does not replace your best-ex process.",
    },
    {
        "title": "Business continuity",
        "body": "Confirm cron, dashboard, and halt file are covered in your BCP if automation is material to daily ops.",
    },
]

_DISCLAIMER = (
    "Fortress Morning Brief is informational and operational context only. "
    "Not investment, tax, or legal advice. You remain responsible for all "
    "decisions and regulatory obligations."
)


def _alpaca_open_symbols() -> list[str]:
    """Open stock symbols from Alpaca when keys are configured (paper vs live from ALPACA_BASE_URL)."""
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    sec = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    if not key or not sec:
        return []
    try:
        from alpaca.trading.client import TradingClient
        from utils.alpaca_env import is_alpaca_paper

        client = TradingClient(key, sec, paper=is_alpaca_paper())
        return [str(p.symbol) for p in client.get_all_positions()]
    except Exception:
        return []


def _load_positions(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / "positions.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return list(raw.get("positions") or [])
        if isinstance(raw, list):
            return raw
    except Exception:
        pass
    return []


def _macro_pulse() -> dict[str, Any]:
    now = time.time()
    if _MACRO_CACHE["v"] is not None and now - float(_MACRO_CACHE["t"]) < _MACRO_TTL_SEC:
        return _MACRO_CACHE["v"]
    out: dict[str, Any] = {}
    try:
        import yfinance as yf
    except Exception:
        return {"error": "yfinance_unavailable"}

    for sym, label in [("^GSPC", "spx"), ("^VIX", "vix"), ("^IXIC", "nasdaq")]:
        try:
            h = yf.Ticker(sym).history(period="6d", auto_adjust=True)
            if h is None or h.empty or len(h["Close"]) < 2:
                continue
            close = h["Close"].astype(float)
            last = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            chg = round((last / prev - 1.0) * 100.0, 2) if prev else None
            out[label] = {"symbol": sym, "last": round(last, 2), "chg_pct_1d": chg}
        except Exception:
            continue
    _MACRO_CACHE["t"] = now
    _MACRO_CACHE["v"] = out
    return out


def _book_rows(tickers: list[str], now_et: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not tickers:
        return rows
    key = tuple(sorted(tickers[:18]))
    now = time.time()
    if (
        _BOOK_CACHE["v"]
        and _BOOK_CACHE["key"] == key
        and now - float(_BOOK_CACHE["t"]) < _BOOK_TTL_SEC
    ):
        return _BOOK_CACHE["v"]
    try:
        import yfinance as yf
    except Exception:
        return [{"ticker": t, "note": "yfinance unavailable"} for t in tickers[:12]]

    today = now_et.date()
    horizon = today + timedelta(days=10)
    for t in tickers[:18]:
        row: dict[str, Any] = {"ticker": t}
        try:
            tk = yf.Ticker(t)
            h = tk.history(period="6d", auto_adjust=True)
            if h is not None and not h.empty and len(h["Close"]) >= 2:
                c = h["Close"].astype(float)
                row["chg_pct_1d"] = round((float(c.iloc[-1]) / float(c.iloc[-2]) - 1.0) * 100.0, 2)
            try:
                ed = tk.get_earnings_dates(limit=12)
            except Exception:
                ed = None
            if ed is not None and not ed.empty:
                for idx in ed.index[:8]:
                    try:
                        d = idx.date() if hasattr(idx, "date") else idx
                        if isinstance(d, datetime):
                            d = d.date()
                        if not isinstance(d, date):
                            continue
                        if today <= d <= horizon:
                            row["earnings_within_10d"] = d.isoformat()
                            break
                    except Exception:
                        continue
        except Exception as exc:
            row["note"] = str(exc)[:80]
        rows.append(row)
    _BOOK_CACHE["t"] = now
    _BOOK_CACHE["key"] = key
    _BOOK_CACHE["v"] = rows
    return rows


def build_operator_morning_brief(
    *,
    data_dir: Path,
    health_excerpt: dict[str, Any] | None = None,
    safety_excerpt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from utils.market_calendar import is_us_equity_rth_open, nyse_closed_full_day, session_label
    from utils.operator_halt import get_halt_state

    now_et = datetime.now(_ET)
    positions = _load_positions(data_dir)
    tickers: list[str] = []
    _seen: set[str] = set()
    for p in positions:
        t = str(p.get("ticker") or "").strip().upper()
        if t and t not in _seen:
            _seen.add(t)
            tickers.append(t)
    alpaca_syms = _alpaca_open_symbols()
    book_source = "positions.json"
    if alpaca_syms:
        for s in alpaca_syms:
            su = str(s).strip().upper()
            if su and su not in _seen:
                _seen.add(su)
                tickers.append(su)
        if not positions and alpaca_syms:
            book_source = "alpaca_open_positions"
        elif positions and alpaca_syms:
            book_source = "positions.json+alpaca"
    positions_book_count = len(tickers)
    tickers = tickers[:24]

    cal = {
        "now_et": now_et.strftime("%Y-%m-%d %H:%M %Z"),
        "session": session_label(now_et),
        "rth_open": is_us_equity_rth_open(now_et),
        "nyse_full_day_closed": nyse_closed_full_day(now_et.date()),
    }

    halt = get_halt_state()
    effective_halt = bool(halt.get("effective_halted"))

    stack_items: list[dict[str, Any]] = [
        {
            "id": "trading_halt",
            "ok": not effective_halt,
            "text": "Kill switch: effective halt should be OFF unless you intend to block submissions.",
        },
    ]

    he = health_excerpt or {}
    cron_ok = bool(he.get("cron_configured"))
    stack_items.append({
        "id": "cron",
        "ok": cron_ok,
        "text": f"Cron jobs detected: {he.get('cron_count', 0)} marker(s) in aggregate scan.",
    })
    val_errs = he.get("validation_errors") or []
    stack_items.append({
        "id": "validation",
        "ok": len(val_errs) == 0,
        "text": "No import validation errors on dashboard check." if not val_errs else f"Validation issues: {len(val_errs)} (see System Health).",
    })

    se = safety_excerpt or {}
    stack_items.append({
        "id": "circuit_breaker",
        "ok": not bool(se.get("circuit_breaker_active")),
        "text": "Risk circuit breaker should be OFF unless stress mode is intentional.",
    })

    drift_path = data_dir / "drift_report.json"
    drift_alert = None
    if drift_path.exists():
        try:
            drift_alert = json.loads(drift_path.read_text(encoding="utf-8")).get("drift_alert")
        except Exception:
            pass
    stack_items.append({
        "id": "drift",
        "ok": drift_alert is not True,
        "text": "Drift report: no alert flag." if drift_alert is not True else "Drift alert is ON — review Drift panel.",
    })

    tip = _POLICY_ROTATION[now_et.timetuple().tm_yday % len(_POLICY_ROTATION)]

    return {
        "timestamp": datetime.now().isoformat(),
        "disclaimer": _DISCLAIMER,
        "calendar": cal,
        "macro": _macro_pulse(),
        "policy_tip": tip,
        "stack": {
            "items": stack_items,
            "positions_count": positions_book_count,
            "book_source": book_source,
            "tickers": tickers,
            "halt": halt,
        },
        "book": _book_rows(tickers, now_et),
    }
