"""
SPY intraday swing agent — session VWAP ladders, ES context, shadow JSONL.
See docs/SPY_INTRADAY_SWING_AGENT_SKETCH.md. Not investment advice.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytz

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    fh = logging.FileHandler(log_dir / "spy_swing.log")
    fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)

ET = pytz.timezone("America/New_York")
SYMBOL_SPY = "SPY"
SYMBOL_ES = "ES=F"

# Session clock (ET)
T_OPEN = time(9, 30)
T_START = time(9, 45)
T_NO_NEW = time(15, 30)
T_FLAT = time(15, 55)

# Ladder bands: (long_low, long_high), (short_low, short_high) as % d_VWAP
BANDS_LONG = {0: (-0.22, 0.06), 1: (-0.38, 0.12), 2: (-0.60, 0.18)}
BANDS_SHORT = {0: (0.06, 0.22), 1: (0.12, 0.38), 2: (0.18, 0.60)}
RUNG_THRESH = (0.10, 0.18)  # R_sigma edges L0/L1/L2

MAX_NOTIONAL_PCT = 0.10
MAX_RISK_PCT = 0.01
MIN_BARS = 8


def _to_et_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    out.index = out.index.tz_convert(ET)
    return out


def _filter_session_day(df: pd.DataFrame, day: date) -> pd.DataFrame:
    if df.empty:
        return df
    idx = df.index
    mask = pd.Series([d.date() == day for d in idx], index=idx)
    return df.loc[mask]


def _session_time_mask(df: pd.DataFrame) -> pd.Series:
    idx = df.index
    return pd.Series([T_OPEN <= t.time() <= time(16, 0) for t in idx], index=idx)


def typical_price(df: pd.DataFrame) -> pd.Series:
    return (df["High"] + df["Low"] + df["Close"]) / 3.0


def session_vwap(df: pd.DataFrame) -> float:
    if df.empty:
        return float("nan")
    tp = typical_price(df)
    vol = df["Volume"].replace(0, np.nan)
    w = tp * vol
    s = vol.sum()
    if s == 0 or np.isnan(s):
        return float(df["Close"].iloc[-1])
    return float(w.sum() / s)


def wilder_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return float("nan")
    h, l, c = df["High"], df["Low"], df["Close"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return float(atr.iloc[-1])


def rsi_14(closes: pd.Series) -> float:
    s = closes.dropna()
    if len(s) < 15:
        return 50.0
    delta = s.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    ag = gain.ewm(alpha=1.0 / 14, adjust=False).mean()
    al = loss.ewm(alpha=1.0 / 14, adjust=False).mean()
    if float(al.iloc[-1]) == 0:
        return 100.0
    rs = float(ag.iloc[-1]) / float(al.iloc[-1])
    return float(100.0 - (100.0 / (1.0 + rs)))


def session_range_pct(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    lo, hi = float(df["Low"].min()), float(df["High"].max())
    c = float(df["Close"].iloc[-1])
    if c <= 0:
        return 0.0
    return (hi - lo) / c * 100.0


def vol_rung(r_sigma: float) -> int:
    if r_sigma < RUNG_THRESH[0]:
        return 0
    if r_sigma < RUNG_THRESH[1]:
        return 1
    return 2


def r3_return(closes: pd.Series) -> float:
    if len(closes) < 4:
        return 0.0
    a, b = float(closes.iloc[-4]), float(closes.iloc[-1])
    if a == 0:
        return 0.0
    return (b - a) / a * 100.0


def opening_range_bounds(df: pd.DataFrame) -> tuple[float | None, float | None]:
    """ORH, ORL for 09:30–09:59 ET."""
    if df.empty:
        return None, None
    chunk = df.between_time("09:30", "09:59", inclusive="both")
    if chunk.empty:
        return None, None
    return float(chunk["High"].max()), float(chunk["Low"].min())


def es_flags(es_df: pd.DataFrame) -> tuple[bool, bool, float]:
    """es_risk_on, es_risk_off, d_vwap_es_pct (last closed bar context)."""
    if es_df is None or es_df.empty or len(es_df) < 4:
        return False, True, float("nan")
    vw = session_vwap(es_df)
    c = float(es_df["Close"].iloc[-1])
    dvw = (c - vw) / vw * 100.0 if vw and vw == vw else 0.0
    r3 = r3_return(es_df["Close"])
    on = c >= vw and r3 > 0
    off = c < vw or r3 < 0
    return on, off, dvw


def fetch_5m(symbol: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        df = t.history(period="1d", interval="5m")
        if df.empty:
            return None
        return _to_et_index(df)
    except Exception as e:
        logger.warning("fetch_5m %s: %s", symbol, e)
        return None


def min_stop_pct(rung: int) -> float:
    return {0: 0.18, 1: 0.22, 2: 0.28}.get(rung, 0.22)


def compute_shares(
    equity: float,
    entry: float,
    rung: int,
) -> int:
    """Cap by 10% notional and ~1% equity risk to initial stop distance."""
    if entry <= 0 or equity <= 0:
        return 0
    max_n = equity * MAX_NOTIONAL_PCT
    risk_budget = equity * MAX_RISK_PCT
    d_stop = min_stop_pct(rung) / 100.0 * entry
    if d_stop <= 0:
        return 0
    by_risk = int(risk_budget // d_stop)
    by_notional = int(max_n // entry)
    shares = max(0, min(by_risk, by_notional))
    return max(0, shares)


def evaluate_spy_swing(
    spy_df: pd.DataFrame,
    es_df: pd.DataFrame | None,
    now_et: datetime,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": True,
        "ts": now_et.isoformat(),
        "phase": "acquire",
        "suggested_action": "no_trade",
        "side": None,
        "score": 0,
        "reason_codes": [],
        "vol_rung": None,
        "d_vwap_pct": None,
        "es_risk_on": None,
        "r3_spy": None,
        "execute_ready": False,
        "shares": 0,
        "symbol": SYMBOL_SPY,
    }

    tnow = now_et.time()
    if tnow < T_START or tnow > time(15, 50):
        out["reason_codes"].append("outside_trading_window")
        return out
    if tnow > T_NO_NEW:
        out["reason_codes"].append("no_new_entries_after_1530")
        return out

    day = now_et.date()
    spy = _filter_session_day(spy_df, day)
    spy = spy.loc[_session_time_mask(spy)]
    if len(spy) < MIN_BARS:
        out["reason_codes"].append("insufficient_bars")
        out["ok"] = False
        return out

    vwap = session_vwap(spy)
    c = float(spy["Close"].iloc[-1])
    d_vwap = (c - vwap) / vwap * 100.0 if vwap else 0.0
    out["d_vwap_pct"] = round(d_vwap, 4)

    atr = wilder_atr(spy, 14)
    atr_pct = (atr / c * 100.0) if c and atr == atr else 0.0
    rng_pct = session_range_pct(spy)
    r_sigma = max(atr_pct, 0.5 * rng_pct)
    rung = vol_rung(r_sigma)
    out["vol_rung"] = rung
    out["r_sigma"] = round(r_sigma, 5)

    r3 = r3_return(spy["Close"])
    out["r3_spy"] = round(r3, 4)

    es_on, es_off, _ = es_flags(es_df if es_df is not None else pd.DataFrame())
    out["es_risk_on"] = es_on
    out["es_risk_off"] = es_off

    rsi = rsi_14(spy["Close"])
    orh, orl = opening_range_bounds(spy)
    or_mid = (orh + orl) / 2.0 if orh is not None and orl is not None else None

    bl, bh = BANDS_LONG[rung]
    long_band_ok = bl <= d_vwap <= min(0.05, bh)
    long_knife = r3 > -0.25
    score_l = 0
    rc_l: list[str] = []
    if 32 <= rsi <= 58:
        score_l += 1
        rc_l.append("rsi_long_zone")
    if or_mid is not None and c >= or_mid:
        score_l += 1
        rc_l.append("or_long_align")
    elif or_mid is None:
        score_l += 1
        rc_l.append("or_unavailable_neutral")

    if es_on and long_band_ok and long_knife and score_l >= 2:
        out["suggested_action"] = "consider_long"
        out["side"] = "long"
        out["score"] = score_l
        out["execute_ready"] = True
        out["reason_codes"] = ["long_setup"] + rc_l
        return out

    sl, sh = BANDS_SHORT[rung]
    short_band_ok = max(-0.05, sl) <= d_vwap <= sh
    short_knife = r3 < 0.25
    score_s = 0
    rc_s: list[str] = []
    if 42 <= rsi <= 68:
        score_s += 1
        rc_s.append("rsi_short_zone")
    if or_mid is not None and c <= or_mid:
        score_s += 1
        rc_s.append("or_short_align")
    elif or_mid is None:
        score_s += 1
        rc_s.append("or_unavailable_neutral")

    if es_off and short_band_ok and short_knife and score_s >= 2:
        out["suggested_action"] = "consider_short"
        out["side"] = "short"
        out["score"] = score_s
        out["execute_ready"] = False
        out["reason_codes"] = ["short_setup_shadow_only"] + rc_s
        return out

    out["reason_codes"] = ["no_setup"]
    return out


def _shadow_path(data_dir: Path, day: date) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / f"spy_swing_shadow_{day.strftime('%Y%m%d')}.jsonl"


def append_shadow_record(data_dir: Path, record: dict[str, Any], day: date | None = None) -> Path:
    p = _shadow_path(data_dir, day or datetime.now(ET).date())
    with open(p, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return p


def run_spy_swing_cycle(
    *,
    shadow_only: bool = True,
    portfolio_equity: float = 20_000.0,
    data_dir: Path | None = None,
    now_et: datetime | None = None,
    spy_df: pd.DataFrame | None = None,
    es_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    One evaluation cycle. Fetches yfinance 5m SPY/ES unless dataframes provided.
    Appends shadow JSONL always. When shadow_only=False, caller may execute (orchestrator).
    """
    data_dir = data_dir or Path("data")
    if now_et is None:
        now_et = datetime.now(ET)
    elif now_et.tzinfo is None:
        now_et = ET.localize(now_et)

    if spy_df is None:
        spy_df = fetch_5m(SYMBOL_SPY)
    if es_df is None:
        es_df = fetch_5m(SYMBOL_ES)

    if spy_df is None or spy_df.empty:
        rec = {
            "ok": False,
            "error": "no_spy_data",
            "ts": now_et.isoformat(),
        }
        append_shadow_record(data_dir, rec, now_et.date())
        return rec

    spy_df = _to_et_index(spy_df)
    if es_df is not None and not es_df.empty:
        es_df = _to_et_index(es_df)

    ev = evaluate_spy_swing(spy_df, es_df, now_et)
    day_spy = _filter_session_day(spy_df, now_et.date())
    day_spy = day_spy.loc[_session_time_mask(day_spy)]
    c = float(day_spy["Close"].iloc[-1]) if not day_spy.empty else float(spy_df["Close"].iloc[-1])
    rung = int(ev.get("vol_rung") if ev.get("vol_rung") is not None else 1)
    ev["reference_price"] = c
    ev["shares"] = compute_shares(portfolio_equity, c, rung) if ev.get("side") == "long" else 0
    ev["shadow_only"] = shadow_only
    append_shadow_record(data_dir, ev, now_et.date())
    logger.info("spy_swing: %s", ev.get("suggested_action"))
    return ev
