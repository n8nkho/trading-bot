"""Unit tests for agents.spy_intraday_swing (no Alpaca; no network when using fixtures)."""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytz

from agents.spy_intraday_swing import (
    compute_shares,
    evaluate_spy_swing,
    min_stop_pct,
    session_vwap,
    vol_rung,
)
from agents import spy_intraday_swing as m


def _bars_etf(day_str: str = "2024-06-12", n: int = 20, base: float = 500.0) -> pd.DataFrame:
    tz = "America/New_York"
    idx = pd.date_range(f"{day_str} 09:30", periods=n, freq="5min", tz=tz)
    r = pd.Series(range(n), index=idx, dtype=float)
    close = base + r * -0.15 + 2.0
    high = close + 0.2
    low = close - 0.2
    vol = pd.Series([1_000_000 + i * 5000 for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


def _es_bull(day_str: str = "2024-06-12", n: int = 20, base: float = 5300.0) -> pd.DataFrame:
    tz = "America/New_York"
    idx = pd.date_range(f"{day_str} 09:30", periods=n, freq="5min", tz=tz)
    r = pd.Series(range(n), index=idx, dtype=float)
    close = base + r * 0.5
    high = close + 1
    low = close - 1
    vol = pd.Series([50_000 + i * 100 for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


class TestSpyIntradaySwing(unittest.TestCase):
    def test_vol_rung_and_min_stop(self):
        self.assertEqual(vol_rung(0.05), 0)
        self.assertEqual(vol_rung(0.12), 1)
        self.assertEqual(vol_rung(0.25), 2)
        self.assertAlmostEqual(min_stop_pct(0), 0.18)

    def test_session_vwap_finite(self):
        df = _bars_etf()
        v = session_vwap(df)
        self.assertFalse(pd.isna(v))
        self.assertGreater(v, 400)

    def test_evaluate_synthetic(self):
        spy = _bars_etf()
        es = _es_bull()
        et = pytz.timezone("America/New_York")
        now = et.localize(datetime(2024, 6, 12, 11, 0, 0))
        out = evaluate_spy_swing(spy, es, now)
        self.assertTrue(out["ok"])
        self.assertIn(out["suggested_action"], ("consider_long", "consider_short", "no_trade"))
        self.assertIsNotNone(out.get("vol_rung"))

    def test_compute_shares_5k(self):
        sh = compute_shares(5000.0, 500.0, 1)
        self.assertGreaterEqual(sh, 0)

    def test_run_cycle_fixture(self):
        spy = _bars_etf()
        es = _es_bull()
        et = pytz.timezone("America/New_York")
        now = et.localize(datetime(2024, 6, 12, 11, 0, 0))
        tmp = Path(__file__).resolve().parent / "_tmp_spy_swing_test"
        tmp.mkdir(exist_ok=True)
        try:
            out = m.run_spy_swing_cycle(
                shadow_only=True,
                portfolio_equity=5000.0,
                data_dir=tmp,
                now_et=now,
                spy_df=spy,
                es_df=es,
            )
            self.assertTrue(out.get("ok"))
            shadow_files = list(tmp.glob("spy_swing_shadow_*.jsonl"))
            self.assertEqual(len(shadow_files), 1)
            line = shadow_files[0].read_text().strip().splitlines()[-1]
            self.assertIn("suggested_action", json.loads(line))
        finally:
            for p in tmp.glob("spy_swing_shadow_*.jsonl"):
                p.unlink(missing_ok=True)
            try:
                tmp.rmdir()
            except OSError:
                pass

    def test_outside_window(self):
        spy = _bars_etf()
        es = _es_bull()
        et = pytz.timezone("America/New_York")
        now = et.localize(datetime(2024, 6, 12, 8, 0, 0))
        out = evaluate_spy_swing(spy, es, now)
        self.assertIn("outside_trading_window", out.get("reason_codes", []))


if __name__ == "__main__":
    unittest.main()
