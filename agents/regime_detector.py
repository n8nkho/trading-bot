#!/usr/bin/env python3
"""Market regime detection with parameter outputs into daily_risk_params."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from utils.atomic_json import read_json, write_json_atomic
from utils.fortress_logger import append_log

REGIMES = ["TRENDING_BULL", "TRENDING_BEAR", "RANGING", "VOLATILE", "CRISIS"]

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_RISK = _DATA / "daily_risk_params.json"
_ENABLED = os.getenv("FORTRESS_REGIME_DETECTION_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


class RegimeDetector:
    def _fetch_regime_data(self, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return {
                "spy_close": 530.0,
                "spy_ma20": 520.0,
                "spy_1d_pct": 0.4,
                "spy_5d_pct": 1.3,
                "vix": 16.5,
                "vix_5d_delta": -0.6,
                "avg_range_10d_pct": 0.95,
                "adv_dec_ratio": 1.4,
                "sector_leaders": ["Technology", "Communication Services"],
                "sector_laggards": ["Utilities"],
            }
        spy = yf.Ticker("SPY").history(period="3mo", interval="1d")
        vix = yf.Ticker("^VIX").history(period="1mo", interval="1d")
        if spy.empty or vix.empty or len(spy) < 25:
            raise RuntimeError("insufficient SPY/VIX data")
        close = spy["Close"]
        ma20 = close.rolling(20).mean().iloc[-1]
        one_d = (close.iloc[-1] / close.iloc[-2] - 1.0) * 100.0
        five_d = (close.iloc[-1] / close.iloc[-6] - 1.0) * 100.0
        ranges = ((spy["High"] - spy["Low"]) / spy["Close"]).tail(10) * 100.0
        vix_close = float(vix["Close"].iloc[-1])
        vix_5d = float(vix["Close"].iloc[-1] - vix["Close"].iloc[-6]) if len(vix) >= 6 else 0.0
        return {
            "spy_close": float(close.iloc[-1]),
            "spy_ma20": float(ma20),
            "spy_1d_pct": float(one_d),
            "spy_5d_pct": float(five_d),
            "vix": vix_close,
            "vix_5d_delta": float(vix_5d),
            "avg_range_10d_pct": float(ranges.mean()),
            "adv_dec_ratio": 1.0,  # Approximation placeholder.
            "sector_leaders": [],
            "sector_laggards": [],
        }

    def _classify(self, data: dict[str, Any]) -> tuple[str, float]:
        spy_close = float(data["spy_close"])
        ma20 = float(data["spy_ma20"])
        vix = float(data["vix"])
        one_d = float(data["spy_1d_pct"])
        avg_rng = float(data["avg_range_10d_pct"])
        if vix > 35 or one_d <= -3.0:
            return "CRISIS", 0.95
        if vix > 25 or avg_rng > 1.5:
            return "VOLATILE", 0.85
        if spy_close > ma20 and vix < 18:
            return "TRENDING_BULL", 0.8
        if spy_close < ma20 and vix > 20:
            return "TRENDING_BEAR", 0.8
        return "RANGING", 0.7

    def _get_regime_params(self, regime: str) -> dict[str, Any]:
        table = {
            "TRENDING_BULL": {
                "screener_min_score": 60,
                "max_concurrent_positions": 6,
                "position_size_multiplier": 1.0,
                "preferred_exit_tier": "T3",
                "critique_strictness": "NORMAL",
            },
            "TRENDING_BEAR": {
                "screener_min_score": 75,
                "max_concurrent_positions": 3,
                "position_size_multiplier": 0.6,
                "preferred_exit_tier": "T1",
                "critique_strictness": "STRICT",
            },
            "RANGING": {
                "screener_min_score": 70,
                "max_concurrent_positions": 4,
                "position_size_multiplier": 0.8,
                "preferred_exit_tier": "T1",
                "critique_strictness": "NORMAL",
            },
            "VOLATILE": {
                "screener_min_score": 80,
                "max_concurrent_positions": 2,
                "position_size_multiplier": 0.4,
                "preferred_exit_tier": "T1",
                "critique_strictness": "STRICT",
            },
            "CRISIS": {
                "screener_min_score": 999,
                "max_concurrent_positions": 0,
                "position_size_multiplier": 0.0,
                "halt_new_entries": True,
                "critique_strictness": "HALT",
            },
        }
        return dict(table.get(regime, table["RANGING"]))

    def detect_regime(self, dry_run: bool = False) -> dict[str, Any]:
        data = self._fetch_regime_data(dry_run=dry_run)
        regime, conf = self._classify(data)
        params = self._get_regime_params(regime)
        out = {
            "regime": regime,
            "regime_confidence": conf,
            "regime_detected_at": datetime.now(timezone.utc).isoformat(),
            "regime_params": params,
            "inputs": data,
            "dry_run": dry_run,
        }
        append_log("regime.log", f"{out['regime_detected_at']} regime={regime} conf={conf:.2f}")
        if not dry_run and _ENABLED:
            doc = read_json(_RISK, default={})
            if not isinstance(doc, dict):
                doc = {}
            doc.update(
                {
                    "regime": regime,
                    "regime_confidence": conf,
                    "regime_detected_at": out["regime_detected_at"],
                    "regime_params": params,
                }
            )
            write_json_atomic(_RISK, doc)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fortress regime detector")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out = RegimeDetector().detect_regime(dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
