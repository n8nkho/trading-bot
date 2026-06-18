#!/usr/bin/env python3
"""Autonomous prompt evolution based on reflection-score deterioration."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.atomic_json import read_json, write_json_atomic
from utils.fortress_logger import append_log
from utils.llm_router import LLMRouter

PROMPT_STORE_PATH = "data/prompt_store.json"
_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_REFL = _DATA / "reflection_log.json"
_STORE = _ROOT / PROMPT_STORE_PATH
_ENABLED = os.getenv("FORTRESS_PROMPT_EVOLUTION_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


class PromptEvolutionAgent:
    def _reflection_records(self) -> list[dict[str, Any]]:
        doc = read_json(_REFL, default={"records": [], "entries": []})
        if not isinstance(doc, dict):
            return []
        rows = doc.get("records")
        if isinstance(rows, list):
            return rows
        rows = doc.get("entries")
        return rows if isinstance(rows, list) else []

    def _should_trigger(self, rows: list[dict[str, Any]]) -> tuple[bool, float]:
        vals = []
        for r in rows[-30:]:
            try:
                vals.append(float(r.get("score")))
            except Exception:
                continue
        if len(vals) < 3:
            return False, 10.0
        last3 = vals[-3:]
        avg = sum(last3) / 3.0
        return avg < 6.0 and all(v < 6.0 for v in last3), avg

    def _analyze_failures(self, poor_rows: list[dict[str, Any]], dry_run: bool) -> dict[str, Any]:
        if dry_run:
            return {
                "failure_patterns": ["late exits", "overweight momentum", "insufficient risk context"],
                "root_cause": "prompt underweights downside catalysts",
                "suggested_prompt_improvements": ["demand bear thesis", "require catalyst confidence", "explicit risk checklist"],
            }
        prompt = (
            "These trade evaluations scored poorly. Identify top 3 systematic failures. "
            "Return JSON with failure_patterns, root_cause, suggested_prompt_improvements.\n"
            f"{json.dumps(poor_rows[-20:], default=str)}"
        )
        raw = LLMRouter().call_deepseek(prompt)
        try:
            return json.loads(str(raw).replace("```json", "").replace("```", "").strip())
        except Exception:
            return {"failure_patterns": [], "root_cause": "parse_fail", "suggested_prompt_improvements": []}

    def _generate_variant(self, current_prompt: str, patterns: list[str], dry_run: bool) -> str:
        if dry_run:
            return current_prompt + "\n- Include explicit downside catalysts and confidence."
        raw = LLMRouter().call_xai(
            "Improve this prompt while preserving output schema.\n"
            f"Current:\n{current_prompt}\n\nPatterns:\n{json.dumps(patterns)}"
        )
        return str(raw).strip() or current_prompt

    def run(self, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
        rows = self._reflection_records()
        trigger, avg = self._should_trigger(rows)
        if not force and not trigger:
            msg = f"{datetime.now(timezone.utc).isoformat()} No evolution needed (avg={avg:.2f})"
            append_log("prompt_evolution.log", msg)
            return {"triggered": False, "avg_score": avg, "message": msg}

        poor = [r for r in rows if isinstance(r, dict) and float(r.get("score", 10) or 10) < 6.0]
        fail = self._analyze_failures(poor, dry_run=dry_run)
        current_pass1 = (
            "You are a bullish analyst evaluating a potential trade. "
            'Respond with JSON: {"decision":"BUY|SELL","confidence":0-1,"reasoning":"..."}'
        )
        current_pass2 = (
            "You are a skeptical risk officer. "
            'Respond with JSON: {"verdict":"CONFIRM|MODIFY|REJECT","critique":"..."}'
        )
        var_a1 = self._generate_variant(current_pass1, fail.get("failure_patterns", []), dry_run=dry_run)
        var_a2 = self._generate_variant(current_pass2, fail.get("failure_patterns", []), dry_run=dry_run)
        var_b1 = self._generate_variant(current_pass1, fail.get("suggested_prompt_improvements", []), dry_run=dry_run)
        var_b2 = self._generate_variant(current_pass2, fail.get("suggested_prompt_improvements", []), dry_run=dry_run)

        now = datetime.now(timezone.utc).isoformat()
        store = {
            "active_variant": "variant_a",
            "evolution_triggered_at": now,
            "trigger_avg_score": avg,
            "failure_patterns": fail.get("failure_patterns", []),
            "variants": {
                "control": {
                    "pass1_prompt": current_pass1,
                    "pass2_prompt": current_pass2,
                    "avg_score": avg,
                    "trade_count": len(rows),
                    "active_since": now,
                },
                "variant_a": {
                    "pass1_prompt": var_a1,
                    "pass2_prompt": var_a2,
                    "avg_score": None,
                    "trade_count": 0,
                    "active_since": now,
                },
                "variant_b": {
                    "pass1_prompt": var_b1,
                    "pass2_prompt": var_b2,
                    "avg_score": None,
                    "trade_count": 0,
                    "active_since": None,
                },
            },
            "note": "Integration hook into critique_loop intentionally not auto-applied by this agent.",
        }
        append_log("prompt_evolution.log", f"{now} evolution_trigger avg={avg:.2f} force={force}")
        if not dry_run and _ENABLED:
            candidate_id = str(store.get("active_variant") or "variant_a")
            try:
                from utils.prompt_walk_forward_gate import ensure_gate_before_promotion

                ensure_gate_before_promotion(
                    candidate_id,
                    metadata={"trigger_avg_score": avg, "source": "prompt_evolution_agent"},
                )
            except RuntimeError as exc:
                append_log("prompt_evolution.log", f"{now} promotion_blocked ledger_health={exc}")
                return {
                    "triggered": True,
                    "avg_score": avg,
                    "store": store,
                    "dry_run": dry_run,
                    "promotion_blocked": str(exc),
                    # Legacy wire value; means ledger health gate failed (not per-candidate WF).
                    "disposition": "pending_walk_forward_fail",
                    "disposition_label": "pending_ledger_health_fail",
                }
            write_json_atomic(_STORE, store)
        return {"triggered": True, "avg_score": avg, "store": store, "dry_run": dry_run}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fortress prompt evolution agent")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = PromptEvolutionAgent().run(dry_run=args.dry_run, force=args.force)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
