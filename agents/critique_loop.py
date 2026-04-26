#!/usr/bin/env python3
"""
Two-pass entry critique: DeepSeek bull + xAI bear/critique.
CONFIRM → full size; MODIFY → 50% size; REJECT → skip.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.fortress_logger import FortressLogger
from utils.llm_router import LLMRouter

_logger = FortressLogger("critique")


def _parse_json_response(text: str) -> dict[str, Any] | None:
    if not text or not str(text).strip():
        return None
    t = str(text).strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.I)
        if m:
            t = m.group(1).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", t):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _pass1_fallback(signal: dict[str, Any]) -> dict[str, Any]:
    d = str(signal.get("direction", "BUY")).upper()
    if d not in ("BUY", "SELL"):
        d = "BUY"
    conf = float(signal.get("confidence", 0.5) or 0.5)
    conf = max(0.0, min(1.0, conf))
    return {"decision": d, "confidence": conf, "reasoning": "fallback from signal"}


def _pass2_fallback(pass1: dict[str, Any]) -> dict[str, Any]:
    conf = float(pass1.get("confidence", 0.5) or 0.5)
    if conf >= 0.75:
        verdict = "CONFIRM"
    elif conf >= 0.55:
        verdict = "MODIFY"
    else:
        verdict = "REJECT"
    return {"verdict": verdict, "critique": "rule-based fallback from pass1 confidence"}


def _build_pass1_prompt(signal: dict[str, Any], trade: dict[str, Any]) -> str:
    return (
        "You are a bullish analyst evaluating a potential trade. "
        "Respond with ONLY valid JSON, no markdown:\n"
        '{"decision": "BUY" or "SELL", "confidence": 0.0-1.0, "reasoning": "string"}\n\n'
        f"Signal: {json.dumps(signal, default=str)}\n"
        f"Trade context: {json.dumps(trade, default=str)}"
    )


def _build_pass2_prompt(signal: dict[str, Any], trade: dict[str, Any], pass1: dict[str, Any]) -> str:
    return (
        "You are a skeptical risk officer (bear case). Given the bullish pass below, "
        "respond with ONLY valid JSON, no markdown:\n"
        '{"verdict": "CONFIRM" or "MODIFY" or "REJECT", "critique": "string"}\n\n'
        f"Signal: {json.dumps(signal, default=str)}\n"
        f"Trade: {json.dumps(trade, default=str)}\n"
        f"Bull pass: {json.dumps(pass1, default=str)}"
    )


def evaluate_with_critique(
    signal: dict[str, Any],
    trade: dict[str, Any],
    *,
    router: LLMRouter | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Returns dict with keys: proceed (bool), size_multiplier (float), pass1, pass2,
    verdict, symbol, human_line.
    """
    r = router or LLMRouter()
    sym = trade.get("symbol") or signal.get("symbol") or "?"
    if dry_run:
        pass1 = _pass1_fallback(signal)
        pass2 = _pass2_fallback(pass1)
    else:
        # ── Prompt evolution hook (read-only) ────────────────────────────────
        _pass1_prompt = _build_pass1_prompt(signal, trade)
        _pass2_prompt = _build_pass2_prompt(signal, trade, {})
        try:
            if os.path.exists("data/prompt_store.json"):
                from utils.atomic_json import read_json as _ps_read

                _ps = _ps_read("data/prompt_store.json", default={})
                _active = _ps.get("active_variant", "control")
                if _active and _active != "control":
                    _variant = _ps.get("variants", {}).get(_active, {})
                    if _variant.get("pass1_prompt"):
                        _pass1_prompt = _variant["pass1_prompt"].format(
                            signal=json.dumps(signal, default=str),
                            trade=json.dumps(trade, default=str),
                        )
                    if _variant.get("pass2_prompt"):
                        _pass2_prompt = _variant["pass2_prompt"]
                    try:
                        from utils.fortress_logger import append_critique_log

                        append_critique_log(f"[PROMPT_EVOLUTION] Using variant: {_active}")
                    except Exception:
                        pass
        except Exception:
            pass  # Silent — always fall back to defaults
        # ── End prompt evolution hook ─────────────────────────────────────────

        p1_raw = r.call_deepseek(_pass1_prompt)
        pass1 = _parse_json_response(p1_raw or "") or _pass1_fallback(signal)
        if "decision" not in pass1:
            pass1["decision"] = _pass1_fallback(signal)["decision"]
        if "confidence" not in pass1:
            pass1["confidence"] = _pass1_fallback(signal)["confidence"]
        # Refresh pass2 prompt with pass1 context unless prompt-store override exists.
        _default_p2 = _build_pass2_prompt(signal, trade, pass1)
        try:
            if os.path.exists("data/prompt_store.json"):
                from utils.atomic_json import read_json as _ps_read

                _ps2 = _ps_read("data/prompt_store.json", default={})
                _active2 = _ps2.get("active_variant", "control")
                if _active2 and _active2 != "control":
                    _variant2 = _ps2.get("variants", {}).get(_active2, {})
                    if _variant2.get("pass2_prompt"):
                        _pass2_prompt = _variant2["pass2_prompt"].format(
                            signal=json.dumps(signal, default=str),
                            trade=json.dumps(trade, default=str),
                            pass1=json.dumps(pass1, default=str),
                        )
                    else:
                        _pass2_prompt = _default_p2
                else:
                    _pass2_prompt = _default_p2
            else:
                _pass2_prompt = _default_p2
        except Exception:
            _pass2_prompt = _default_p2
        p2_raw = r.call_xai(_pass2_prompt)
        pass2 = _parse_json_response(p2_raw or "") or _pass2_fallback(pass1)
        if "verdict" not in pass2:
            pass2["verdict"] = _pass2_fallback(pass1)["verdict"]

    verdict = str(pass2.get("verdict", "REJECT")).upper()
    if verdict not in ("CONFIRM", "MODIFY", "REJECT"):
        verdict = "REJECT"

    if verdict == "CONFIRM":
        mult, proceed = 1.0, True
    elif verdict == "MODIFY":
        mult, proceed = 0.5, True
    else:
        mult, proceed = 0.0, False

    p1_dec = str(pass1.get("decision", "?"))
    p1_conf = pass1.get("confidence", "?")
    human = (
        f"[{sym}] Pass1: {p1_dec} (DeepSeek, confidence: {p1_conf}) | "
        f"Pass2: {verdict} (xAI) | Action: "
        + ("ENTER full size" if verdict == "CONFIRM" else "ENTER 50% size" if verdict == "MODIFY" else "SKIP")
    )
    _logger.log_critique(human)
    return {
        "symbol": sym,
        "proceed": proceed,
        "size_multiplier": mult,
        "verdict": verdict,
        "pass1": pass1,
        "pass2": pass2,
        "human_line": human,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Critique loop (two-pass entry)")
    ap.add_argument("--dry-run", action="store_true", help="No LLM calls; rule fallback only")
    args = ap.parse_args()
    sample_signal = {"symbol": "SPY", "direction": "BUY", "confidence": 0.7, "reason": "test"}
    sample_trade = {"symbol": "SPY", "side": "buy", "qty": 1}
    out = evaluate_with_critique(sample_signal, sample_trade, dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    enabled = os.environ.get("FORTRESS_CRITIQUE_LOOP_ENABLED", "").lower() in ("1", "true", "yes")
    if not enabled and "--dry-run" not in sys.argv:
        print(
            "Set FORTRESS_CRITIQUE_LOOP_ENABLED=1 or use --dry-run for CLI test.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise SystemExit(main())
