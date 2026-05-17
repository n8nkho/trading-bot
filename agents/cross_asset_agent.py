#!/usr/bin/env python3
"""Cross-asset intelligence synthesis for equity bias and sector flags."""

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
from utils.llm_router import LLMRouter

CROSS_ASSET_RELATIONSHIPS = {
    "TLT": {"rising": "TECH_BEARISH", "falling": "TECH_BULLISH"},
    "DXY": {"rising": "EMERGING_BEARISH, COMMODITY_BEARISH", "falling": "EMERGING_BULLISH"},
    "GLD": {"rising": "RISK_OFF, UNCERTAINTY", "falling": "RISK_ON"},
    "USO": {"rising": "ENERGY_BULLISH, INFLATION", "falling": "ENERGY_BEARISH"},
    "VIX": {"rising": "BROAD_RISK_OFF", "falling": "BROAD_RISK_ON"},
    "HYG": {"falling": "CREDIT_STRESS, BROAD_BEARISH", "rising": "RISK_ON"},
}

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_OUT = _DATA / "cross_asset_signal.json"
_RISK = _DATA / "daily_risk_params.json"
_ENABLED = os.getenv("FORTRESS_CROSS_ASSET_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


class CrossAssetAgent:
    def _fetch_prices(self, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return {
                "TLT": {"change_1d": -0.8, "change_5d": -1.1},
                "DXY": {"change_1d": 0.4, "change_5d": 1.0},
                "GLD": {"change_1d": 0.2, "change_5d": 0.9},
                "USO": {"change_1d": -0.6, "change_5d": -1.4},
                "VIX": {"change_1d": 1.3, "change_5d": 2.9},
                "HYG": {"change_1d": -0.7, "change_5d": -1.8},
            }
        mapping = {"TLT": "TLT", "DXY": "UUP", "GLD": "GLD", "USO": "USO", "VIX": "^VIX", "HYG": "HYG"}
        out: dict[str, Any] = {}
        for k, s in mapping.items():
            h = yf.Ticker(s).history(period="1mo", interval="1d")
            if h.empty or len(h) < 6:
                continue
            c = h["Close"]
            out[k] = {
                "change_1d": float((c.iloc[-1] / c.iloc[-2] - 1.0) * 100.0),
                "change_5d": float((c.iloc[-1] / c.iloc[-6] - 1.0) * 100.0),
            }
        return out

    def _state(self, pct: float) -> str:
        if pct > 0.5:
            return "RISING"
        if pct < -0.5:
            return "FALLING"
        return "NEUTRAL"

    def run(self, dry_run: bool = False) -> dict[str, Any]:
        data = self._fetch_prices(dry_run=dry_run)
        matrix = []
        for k, v in data.items():
            st = self._state(float(v.get("change_1d", 0.0)))
            implication = ""
            if st == "RISING":
                implication = CROSS_ASSET_RELATIONSHIPS.get(k, {}).get("rising", "")
            elif st == "FALLING":
                implication = CROSS_ASSET_RELATIONSHIPS.get(k, {}).get("falling", "")
            matrix.append({"asset": k, "state": st, "change_1d": v.get("change_1d"), "implication": implication})

        if dry_run:
            llm = {
                "favored_sectors": ["Energy"],
                "avoid_sectors": ["Technology"],
                "overall_bias": "BEARISH",
                "confidence": 7,
                "key_signal": "VIX rising + HYG falling",
                "reasoning": "Risk-off signals dominate.",
            }
        else:
            prompt = (
                "Given these cross-asset signals, return JSON only with keys "
                "favored_sectors, avoid_sectors, overall_bias(BULLISH/NEUTRAL/BEARISH), "
                "confidence(1-10), key_signal, reasoning.\n\n"
                f"{json.dumps(matrix, default=str)}"
            )
            raw = LLMRouter().call_deepseek(prompt)
            try:
                llm = json.loads(str(raw).replace("```json", "").replace("```", "").strip())
            except Exception:
                llm = {
                    "favored_sectors": [],
                    "avoid_sectors": [],
                    "overall_bias": "NEUTRAL",
                    "confidence": 5,
                    "key_signal": "parse_fail",
                    "reasoning": str(raw)[:160],
                }

        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall_bias": str(llm.get("overall_bias", "NEUTRAL")).upper(),
            "confidence": int(llm.get("confidence", 0) or 0),
            "favored_sectors": llm.get("favored_sectors", []),
            "avoid_sectors": llm.get("avoid_sectors", []),
            "key_signal": llm.get("key_signal", ""),
            "reasoning": llm.get("reasoning", ""),
            "matrix": matrix,
            "dry_run": dry_run,
        }
        append_log("cross_asset.log", f"{out['generated_at']} bias={out['overall_bias']} conf={out['confidence']}")
        if not dry_run:
            write_json_atomic(_OUT, out)
            if _ENABLED and out["overall_bias"] == "BEARISH" and out["confidence"] >= 7:
                risk = read_json(_RISK, default={})
                if not isinstance(risk, dict):
                    risk = {}
                flags = risk.get("flags")
                if not isinstance(flags, list):
                    flags = []
                if "CROSS_ASSET_BEARISH" not in flags:
                    flags.append("CROSS_ASSET_BEARISH")
                risk["flags"] = flags
                write_json_atomic(_RISK, risk)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fortress cross-asset agent")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out = CrossAssetAgent().run(dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
