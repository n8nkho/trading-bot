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
from utils.llm_resilience import TokenBucketLimiter, exponential_backoff_retry
from utils.llm_router import LLMRouter

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_OUT = _DATA / "earnings_intel.json"
_DEDUPE = _DATA / "earnings_intel_alert_dedupe.json"
_HEALTH = _DATA / "earnings_llm_health.json"
_ENABLED = os.getenv("FORTRESS_EARNINGS_INTEL_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
_LLM_RPM = float(os.getenv("FORTRESS_EARNINGS_LLM_RPM", "10") or 10.0)
_LLM_LIMITER = TokenBucketLimiter(rate=max(0.5, _LLM_RPM), per_seconds=60.0)

_MATERIAL_ACTIONS = frozenset({"BUY_OPPORTUNITY", "SELL_SIGNAL", "AVOID"})
_STRONG_VERDICTS = frozenset({"STRONG_BEAT", "STRONG_MISS"})


def _rules_based_earnings_score(symbol: str, transcript_text: str) -> dict[str, Any]:
    """Deterministic fallback when LLM providers rate-limit or fail."""
    t = (transcript_text or "").lower()
    score = 0.0
    if any(k in t for k in ("raised guidance", "raise guidance", "beat", "top line beat")):
        score += 1.0
    if any(k in t for k in ("lowered guidance", "miss", "shortfall", "weak demand")):
        score -= 1.0
    if "inline" in t or "in-line" in t:
        score += 0.0
    verdict = "IN_LINE"
    if score >= 1.0:
        verdict = "BEAT"
    elif score <= -1.0:
        verdict = "MISS"
    return {
        "symbol": symbol,
        "verdict": verdict,
        "recommended_action": "HOLD",
        "rules_fallback": True,
        "rules_score": score,
        "reasoning": "rules_fallback_eps_guidance_heuristic",
    }


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


def _touch_llm_health(
    *,
    ok: bool,
    err: str | None = None,
) -> None:
    try:
        doc = read_json(_HEALTH, default={})
        if not isinstance(doc, dict):
            doc = {}
        now = datetime.now(timezone.utc).isoformat()
        window = doc.get("error_events_1h")
        if not isinstance(window, list):
            window = []
        if not ok and err:
            window.append({"ts": now, "err": err[:400]})
        cutoff = time.time() - 3600
        pruned = []
        for ev in window[-200:]:
            try:
                ts = str(ev.get("ts") or "")
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.timestamp() >= cutoff:
                    pruned.append(ev)
            except Exception:
                continue
        errors_1h = len(pruned)
        doc.update(
            {
                "updated_at": now,
                "last_success_at": now if ok else doc.get("last_success_at"),
                "last_error_at": now if not ok else doc.get("last_error_at"),
                "last_error_excerpt": (err or "")[:400] if not ok else doc.get("last_error_excerpt"),
                "error_events_1h": pruned,
                "error_rate_1h": round(errors_1h / max(1.0, _LLM_RPM), 4),
                "queue_depth_hint": _LLM_LIMITER.queue_depth_hint(),
            }
        )
        write_json_atomic(_HEALTH, doc)
    except Exception:
        pass


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
    def _llm_call_bucketed(self, fn_label: str, fn):
        if not _LLM_LIMITER.acquire(1.0):
            append_log("earnings_intel.log", f"{fn_label} skipped — LLM rate bucket saturated (rpm={_LLM_RPM})")
            return None
        return fn()

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
        prompt = f"Provide a short excerpt of latest earnings call transcript for {symbol}. Return plain text."

        @exponential_backoff_retry()
        def _call():
            router = LLMRouter()
            return str(
                router.call_with_fallback(
                    prompt,
                    primary=os.getenv("FORTRESS_EARNINGS_LLM_PRIMARY", "deepseek"),
                    max_tokens=800,
                )
            )

        def _do():
            return _call()[:8000]

        out = self._llm_call_bucketed("fetch_transcript", _do)
        return out or ""

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

        @exponential_backoff_retry()
        def _call():
            router = LLMRouter()
            return router.call_with_fallback(
                prompt,
                primary=os.getenv("FORTRESS_EARNINGS_LLM_PRIMARY", "deepseek"),
                max_tokens=500,
            )

        raw_holder: dict[str, Any] = {}

        def _do():
            raw_holder["raw"] = _call()
            return raw_holder["raw"]

        llm_out = self._llm_call_bucketed("analyze_transcript", _do)
        raw = llm_out if llm_out is not None else ""
        if _llm_upstream_failed(str(raw)):
            fb = _rules_based_earnings_score(symbol, transcript_text)
            append_log(
                "earnings_intel.log",
                f"{symbol} LLM analyze failed; rules_fallback verdict={fb.get('verdict')} ({str(raw)[:120]})",
            )
            _touch_llm_health(ok=False, err=str(raw))
            return fb
        try:
            parsed = json.loads(str(raw).replace("```json", "").replace("```", "").strip())
            _touch_llm_health(ok=True)
            return parsed
        except Exception:
            fb = _rules_based_earnings_score(symbol, transcript_text)
            append_log("earnings_intel.log", f"{symbol} JSON parse failed; rules_fallback used")
            _touch_llm_health(ok=False, err="parse_error")
            return fb

    def run(self, symbol: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        syms = [symbol.upper()] if symbol else self._universe_symbols()
        if not syms:
            syms = ["AAPL"]

        entries = []
        held = set(self._universe_symbols())
        for sym in syms:
            txt = (self._fetch_transcript(sym, dry_run=dry_run) or "").strip()
            if not txt:
                append_log("earnings_intel.log", f"{sym} empty transcript — rules_fallback")
                analysis = _rules_based_earnings_score(sym, "")
            elif _llm_upstream_failed(txt):
                append_log("earnings_intel.log", f"{sym} upstream LLM failure — using rules_fallback ({txt[:180]})")
                # Rules fallback is acceptable; do not spam alerts.log (xAI 403/429 credits).
                analysis = _rules_based_earnings_score(sym, txt)
            else:
                analysis = self._analyze_transcript(sym, txt, dry_run=dry_run)
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
        if not dry_run:
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
