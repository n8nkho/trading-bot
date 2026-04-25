#!/usr/bin/env python3
"""Narrative sentiment velocity and acceleration detector."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json, write_json_atomic
from utils.fortress_logger import append_alerts_log, append_log
from utils.llm_router import LLMRouter

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_OUT = _DATA / "sentiment_velocity.json"
_ENABLED = os.getenv("FORTRESS_SENTIMENT_VELOCITY_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


class SentimentVelocityAgent:
    def _fetch_news_window(self, symbol: str, window_hours: int, dry_run: bool = False) -> list[str]:
        if dry_run:
            return [f"{symbol} mock headline {i} ({window_hours}h)" for i in range(1, 4)]
        prompt = (
            f"Provide up to 8 recent headlines for {symbol} in the last {window_hours} hours. "
            "Return JSON only: {\"headlines\": [\"...\"]}"
        )
        raw = LLMRouter().call_xai(prompt)
        try:
            obj = json.loads(str(raw).replace("```json", "").replace("```", "").strip())
            h = obj.get("headlines", [])
            return [str(x) for x in h][:8] if isinstance(h, list) else []
        except Exception:
            return []

    def _score_sentiment(self, symbol: str, headlines: list[str], dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return {"score": 0.25, "confidence": 0.75, "key_themes": ["mock"]}
        prompt = (
            f"Score sentiment for {symbol} based on these headlines from a time window: "
            "-1.0 to +1.0. Return JSON only {\"score\": float, \"confidence\": float, \"key_themes\": []}\n"
            f"{json.dumps(headlines, default=str)}"
        )
        raw = LLMRouter().call_deepseek(prompt)
        try:
            obj = json.loads(str(raw).replace("```json", "").replace("```", "").strip())
            return {
                "score": float(obj.get("score", 0.0) or 0.0),
                "confidence": float(obj.get("confidence", 0.5) or 0.5),
                "key_themes": obj.get("key_themes", []),
            }
        except Exception:
            return {"score": 0.0, "confidence": 0.0, "key_themes": []}

    def _calculate_velocity(self, scores_by_window: dict[str, float]) -> dict[str, float]:
        v2 = scores_by_window["2h"] - scores_by_window["24h"]
        v24 = scores_by_window["24h"] - scores_by_window["7d"]
        acc = v2 - v24
        return {"velocity_2h_vs_24h": v2, "velocity_24h_vs_7d": v24, "acceleration": acc}

    def _classify(self, velocity: float, acceleration: float) -> str:
        if velocity > 0.3 and acceleration > 0:
            return "SURGING"
        if velocity > 0.1 and acceleration > 0:
            return "BUILDING"
        if abs(velocity) <= 0.1:
            return "STABLE"
        if velocity < -0.3 or acceleration < -0.2:
            return "COLLAPSING"
        return "FADING"

    def run(self, symbols: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
        held_set: set[str] = set()
        if symbols is None:
            positions = read_json(_DATA / "positions.json", default=[])
            if isinstance(positions, dict):
                positions = positions.get("positions", [])
            pos_syms = [str(p.get("underlying_ticker") or p.get("ticker") or "").upper() for p in positions if isinstance(p, dict)]
            held_set = {s for s in pos_syms if s}
            syms = sorted({s for s in pos_syms if s})
        else:
            syms = sorted({str(s).strip().upper() for s in symbols if str(s).strip()})
        if not syms:
            syms = ["SPY"]

        out_symbols: dict[str, Any] = {}
        for sym in syms:
            h2 = self._fetch_news_window(sym, 2, dry_run=dry_run)
            h24 = self._fetch_news_window(sym, 24, dry_run=dry_run)
            h7d = self._fetch_news_window(sym, 24 * 7, dry_run=dry_run)
            s2 = self._score_sentiment(sym, h2, dry_run=dry_run)
            s24 = self._score_sentiment(sym, h24, dry_run=dry_run)
            s7d = self._score_sentiment(sym, h7d, dry_run=dry_run)
            vel = self._calculate_velocity({"2h": s2["score"], "24h": s24["score"], "7d": s7d["score"]})
            cls = self._classify(vel["velocity_2h_vs_24h"], vel["acceleration"])
            signal = "STABLE"
            in_positions = sym in held_set
            if cls == "SURGING":
                signal = "HOLD_EXTEND" if in_positions else "ENTRY_OPPORTUNITY"
            elif cls == "COLLAPSING":
                signal = "EXIT_RISK" if in_positions else "AVOID"
            elif cls in {"BUILDING", "FADING"}:
                signal = "WATCH"
            rec = {
                "score_2h": s2["score"],
                "score_24h": s24["score"],
                "score_7d": s7d["score"],
                "velocity": vel["velocity_2h_vs_24h"],
                "acceleration": vel["acceleration"],
                "classification": cls,
                "signal": signal,
                "key_themes": list(dict.fromkeys((s2.get("key_themes") or []) + (s24.get("key_themes") or [])))[:5],
            }
            out_symbols[sym] = rec
            append_log("sentiment_velocity.log", f"{sym} {cls} velocity={rec['velocity']:.3f} signal={signal}")
            if signal == "EXIT_RISK":
                append_alerts_log(f"EXIT_RISK sentiment collapse for {sym} velocity={rec['velocity']:.3f}")

        out = {"generated_at": datetime.now(timezone.utc).isoformat(), "symbols": out_symbols}
        if not dry_run and _ENABLED:
            write_json_atomic(_OUT, out)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fortress sentiment velocity agent")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--symbols", default="")
    args = ap.parse_args()
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    out = SentimentVelocityAgent().run(symbols=syms, dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
