#!/usr/bin/env python3
"""Options flow intelligence (unusual activity, directional conviction)."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from utils.atomic_json import read_json, write_json_atomic
from utils.fortress_logger import append_alerts_log, append_log
from utils.llm_router import LLMRouter

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_OUT = _DATA / "options_flow.json"
_ENABLED = os.getenv("FORTRESS_OPTIONS_FLOW_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


class OptionsFlowAgent:
    def _fetch_unusual_whales(self, dry_run: bool = False) -> list[dict[str, Any]]:
        if dry_run:
            return [
                {"symbol": "AAPL", "premium": 120000, "type": "CALL", "expiry_days": 5, "otm": True},
                {"symbol": "NVDA", "premium": 90000, "type": "PUT", "expiry_days": 4, "otm": True},
            ]
        # Public API key requirements vary; safe live fallback uses yfinance path.
        return []

    def _fetch_yfinance_unusual_volume(self, symbols: list[str], dry_run: bool = False) -> list[dict[str, Any]]:
        if dry_run:
            return []
        events: list[dict[str, Any]] = []
        for sym in symbols[:20]:
            try:
                tk = yf.Ticker(sym)
                exps = tk.options or []
                if not exps:
                    continue
                chain = tk.option_chain(exps[0])
                for df, t in ((chain.calls, "CALL"), (chain.puts, "PUT")):
                    if df is None or df.empty:
                        continue
                    sample = df.head(20)
                    for _, row in sample.iterrows():
                        vol = float(row.get("volume") or 0)
                        oi = float(row.get("openInterest") or 0)
                        if oi > 0 and vol > 10 * oi:
                            events.append({"symbol": sym, "premium": float(row.get("lastPrice") or 0) * vol * 100, "type": t, "expiry_days": 7, "otm": True, "classification": "UNUSUAL_VOLUME"})
            except Exception:
                continue
        return events

    def _classify(self, e: dict[str, Any]) -> str:
        if e.get("classification"):
            return str(e["classification"])
        t = str(e.get("type", "")).upper()
        premium = float(e.get("premium", 0) or 0)
        expiry = int(e.get("expiry_days", 99) or 99)
        otm = bool(e.get("otm", False))
        if premium > 50000 and expiry < 14 and otm and t == "CALL":
            return "BULLISH_SWEEP"
        if premium > 50000 and expiry < 14 and otm and t == "PUT":
            return "BEARISH_SWEEP"
        return "HEDGE"

    def _score_flow_event(self, event: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            cls = self._classify(event)
            return {"directional": cls in {"BULLISH_SWEEP", "BEARISH_SWEEP"}, "direction": "BULL" if cls == "BULLISH_SWEEP" else ("BEAR" if cls == "BEARISH_SWEEP" else "NEUTRAL"), "conviction": 7 if cls != "HEDGE" else 3, "reasoning": "dry-run classification"}
        raw = LLMRouter().call_deepseek(
            "Given this options flow JSON, decide if directional or hedge. "
            "Return JSON only {directional: bool, direction: BULL/BEAR/NEUTRAL, conviction: int, reasoning: str}\n"
            f"{json.dumps(event, default=str)}"
        )
        try:
            obj = json.loads(str(raw).replace("```json", "").replace("```", "").strip())
            return {
                "directional": bool(obj.get("directional", False)),
                "direction": str(obj.get("direction", "NEUTRAL")).upper(),
                "conviction": int(obj.get("conviction", 0) or 0),
                "reasoning": str(obj.get("reasoning", "")),
            }
        except Exception:
            return {"directional": False, "direction": "NEUTRAL", "conviction": 0, "reasoning": "parse_fail"}

    def run(self, symbols: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
        if symbols is None:
            positions = read_json(_DATA / "positions.json", default=[])
            if isinstance(positions, dict):
                positions = positions.get("positions", [])
            symbols = sorted({str(p.get("underlying_ticker") or p.get("ticker") or "").upper() for p in positions if isinstance(p, dict)})
        events = self._fetch_unusual_whales(dry_run=dry_run)
        if not events:
            events = self._fetch_yfinance_unusual_volume(symbols or [], dry_run=dry_run)

        signals = []
        held = set(symbols or [])
        for e in events:
            cls = self._classify(e)
            sc = self._score_flow_event(e, dry_run=dry_run)
            sig = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": str(e.get("symbol", "")).upper(),
                "classification": cls,
                "flow": e,
                "score": sc,
            }
            signals.append(sig)
            append_log("options_flow.log", f"{sig['symbol']} {cls} directional={sc['directional']} conviction={sc['conviction']}")
            if cls == "BEARISH_SWEEP" and sig["symbol"] in held:
                append_alerts_log(f"BEARISH options sweep on held symbol {sig['symbol']}")

        out = {"generated_at": datetime.now(timezone.utc).isoformat(), "signals": signals}
        if not dry_run and _ENABLED:
            write_json_atomic(_OUT, out)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fortress options flow agent")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--symbols", default="")
    args = ap.parse_args()
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    out = OptionsFlowAgent().run(symbols=syms, dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
