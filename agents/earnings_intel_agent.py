#!/usr/bin/env python3
"""Earnings transcript intelligence (fast post-release parsing)."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from utils.atomic_json import read_json, write_json_atomic
from utils.fortress_logger import append_alerts_log, append_log
from utils.llm_router import LLMRouter

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_OUT = _DATA / "earnings_intel.json"
_ENABLED = os.getenv("FORTRESS_EARNINGS_INTEL_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


class EarningsIntelAgent:
    def _universe_symbols(self) -> list[str]:
        positions = read_json(_DATA / "positions.json", default=[])
        if isinstance(positions, dict):
            positions = positions.get("positions", [])
        ps = {str(p.get("underlying_ticker") or p.get("ticker") or "").upper() for p in positions if isinstance(p, dict)}
        ps.discard("")
        return sorted(ps)

    def _fetch_transcript(self, symbol: str, dry_run: bool = False) -> str:
        if dry_run:
            return f"{symbol} transcript mock: management raised guidance and highlighted margin expansion."
        # Public transcript fetching is source-dependent; use LLM retrieval fallback.
        prompt = f"Provide a short excerpt of latest earnings call transcript for {symbol}. Return plain text."
        return str(LLMRouter().call_xai(prompt))[:8000]

    def _analyze_transcript(self, symbol: str, transcript_text: str, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return {
                "symbol": symbol,
                "verdict": "BEAT",
                "recommended_action": "HOLD",
                "ceo_tone": "confident",
                "reasoning": "Dry-run mock transcript analysis",
            }
        prompt = (
            f"Analyze this earnings call transcript for {symbol}. "
            "Extract revenue/EPS vs expectations, guidance, CEO tone, analyst concerns, hidden signals, "
            "overall verdict (STRONG_BEAT/BEAT/IN_LINE/MISS/STRONG_MISS), recommended action "
            "(BUY_OPPORTUNITY/HOLD/SELL_SIGNAL/AVOID). Return JSON only.\n\n"
            f"{transcript_text[:12000]}"
        )
        raw = LLMRouter().call_xai(prompt)
        try:
            return json.loads(str(raw).replace("```json", "").replace("```", "").strip())
        except Exception:
            return {"symbol": symbol, "verdict": "IN_LINE", "recommended_action": "HOLD", "parse_error": True, "raw_excerpt": str(raw)[:220]}

    def run(self, symbol: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        syms = [symbol.upper()] if symbol else self._universe_symbols()
        if not syms:
            syms = ["AAPL"]

        entries = []
        held = set(self._universe_symbols())
        for sym in syms:
            txt = self._fetch_transcript(sym, dry_run=dry_run)
            if not txt:
                continue
            analysis = self._analyze_transcript(sym, txt, dry_run=dry_run)
            rec = {
                "symbol": sym,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "analysis": analysis,
            }
            entries.append(rec)
            append_log("earnings_intel.log", f"{sym} verdict={analysis.get('verdict')} action={analysis.get('recommended_action')}")
            if sym in held:
                append_alerts_log(f"Earnings intel for held symbol {sym}: {analysis.get('recommended_action')}")

        out = {"entries": entries}
        if not dry_run and _ENABLED:
            doc = read_json(_OUT, default={"entries": []})
            if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
                doc = {"entries": []}
            doc["entries"].extend(entries)
            write_json_atomic(_OUT, doc)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fortress earnings intelligence agent")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--symbol", default=None)
    args = ap.parse_args()
    out = EarningsIntelAgent().run(symbol=args.symbol, dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
