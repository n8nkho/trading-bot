#!/usr/bin/env python3
"""Earnings transcript intelligence (fast post-release parsing)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json, write_json_atomic
from utils.fortress_logger import append_alerts_log, append_log
from utils.llm_router import LLMRouter

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_OUT = _DATA / "earnings_intel.json"
_DEDUPE = _DATA / "earnings_intel_alert_dedupe.json"
_ENABLED = os.getenv("FORTRESS_EARNINGS_INTEL_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}

_MATERIAL_ACTIONS = frozenset({"BUY_OPPORTUNITY", "SELL_SIGNAL", "AVOID"})
_STRONG_VERDICTS = frozenset({"STRONG_BEAT", "STRONG_MISS"})


def _llm_upstream_failed(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    if s.startswith("Error:"):
        return True
    u = s.upper()
    if "INCORRECT API KEY" in u or "INVALID API KEY" in u:
        return True
    if "BADREQUESTERROR" in u or "INVALID ARGUMENT" in u:
        return True
    return False


def _should_alert_held_symbol(analysis: dict[str, Any]) -> bool:
    """Routine IN_LINE + HOLD is noise for operators; alert only material signals."""
    action = str(analysis.get("recommended_action") or "").strip().upper()
    verdict = str(analysis.get("verdict") or "").strip().upper()
    if action in _MATERIAL_ACTIONS:
        return True
    if verdict in _STRONG_VERDICTS:
        return True
    return False


def _maybe_alert_api_failure(reason: str) -> None:
    """At most one Fortress Alerts line per ~6h for LLM/API outages (avoid spam)."""
    now = time.time()
    doc = read_json(_DEDUPE, default={})
    if not isinstance(doc, dict):
        doc = {}
    last = float(doc.get("last_api_failure_alert_ts") or 0.0)
    if now - last < 6 * 3600:
        append_log("earnings_intel.log", f"API/LLM error (deduped, no alerts.log): {reason[:160]}")
        return
    doc["last_api_failure_alert_ts"] = now
    write_json_atomic(_DEDUPE, doc)
    snippet = reason.replace("\n", " ")[:180]
    append_alerts_log(f"Earnings intel: LLM/API failure — {snippet}")


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
        if _llm_upstream_failed(str(raw)):
            return {
                "symbol": symbol,
                "verdict": "IN_LINE",
                "recommended_action": "HOLD",
                "llm_error": True,
                "raw_excerpt": str(raw)[:220],
            }
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
            if _llm_upstream_failed(txt):
                append_log("earnings_intel.log", f"{sym} ERROR upstream LLM: {txt[:240]}")
                _maybe_alert_api_failure(txt)
                continue
            analysis = self._analyze_transcript(sym, txt, dry_run=dry_run)
            if analysis.get("llm_error"):
                ex = str(analysis.get("raw_excerpt") or "")
                append_log("earnings_intel.log", f"{sym} ERROR analyze LLM: {ex[:220]}")
                _maybe_alert_api_failure(ex or "analyze phase LLM failure")
                continue
            rec = {
                "symbol": sym,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "analysis": analysis,
            }
            entries.append(rec)
            append_log("earnings_intel.log", f"{sym} verdict={analysis.get('verdict')} action={analysis.get('recommended_action')}")
            if sym in held and _should_alert_held_symbol(analysis):
                append_alerts_log(f"Earnings intel for held symbol {sym}: {analysis.get('recommended_action')} (verdict={analysis.get('verdict')})")

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
    # Avoid dumping multi-MB JSON into cron-captured logs (pollutes dashboard tails).
    if sys.stdout.isatty():
        print(json.dumps(out, indent=2, default=str))
    else:
        n = len(out.get("entries") or [])
        print(f"earnings_intel_agent ok entries={n}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
