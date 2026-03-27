"""
LLM reasoning engine for trade entry/exit and pattern discovery.

Design goals:
- LLM-first decisions when provider is enabled
- strict JSON output contract
- safe fallback when LLM is unavailable or malformed
"""

from __future__ import annotations

import glob
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.local_llm import call_llm
from utils.llm_learning_context import build_learning_context


logger = logging.getLogger(__name__)

# Paper trading: bias toward learning from current signals, not fearing past streaks.
AGGRESSIVE_PAPER_TRADING_PROMPT = """You are an AGGRESSIVE paper trader learning through experience.

CRITICAL: This is PAPER TRADING — zero real-money risk. Primary goal: take calculated trades to LEARN what works.

REASONING:
1. Judge THIS setup from current technicals (RSI, volume, price), analyst/scout/CIO context, and regime.
2. Do NOT refuse a good setup because of unrelated past losing trades. Streaks are noise; each decision is new data.
3. When signals align (e.g. oversold + volume + supportive analyst), prefer BUY to gather evidence.
4. Size with confidence using position_size_multiplier in [0.8, 1.2].

Return ONLY JSON with keys:
decision (BUY or SKIP),
confidence (0..1),
reasoning (2-3 sentences),
key_factors (array of strings),
risks (array of strings),
expected_outcome (string),
position_size_multiplier (0.8..1.2),
learning_hypothesis (what we might learn from taking or skipping this trade)."""

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
REASONING_HISTORY = DATA_DIR / "llm_reasoning_history.jsonl"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


class LLMReasoningEngine:
    def __init__(self) -> None:
        self.recent_trades = self._load_recent_trades()
        self.reasoning_buffer: list[dict[str, Any]] = []

    def _call(self, system: str, user: str, timeout: int = 30) -> str:
        prompt = f"{system}\n\nUSER CONTEXT:\n{user}"
        return call_llm(prompt, timeout=timeout)

    def evaluate_trade_opportunity(self, candidate: dict[str, Any]) -> dict[str, Any]:
        symbol = str(candidate.get("ticker") or candidate.get("symbol") or "").upper()
        system = AGGRESSIVE_PAPER_TRADING_PROMPT
        user = json.dumps(
            {
                "symbol": symbol,
                "candidate": {
                    "price": candidate.get("current_price") or candidate.get("price"),
                    "rsi": candidate.get("rsi"),
                    "volume_ratio": candidate.get("volume_ratio"),
                    "drop_pct": candidate.get("drop_pct"),
                    "analyst_rec": (candidate.get("analyst_meta") or {}).get("recommendation")
                    if isinstance(candidate.get("analyst_meta"), dict)
                    else candidate.get("analyst_rec"),
                    "scout_score": (candidate.get("agentic_meta") or {}).get("scout_score")
                    if isinstance(candidate.get("agentic_meta"), dict)
                    else candidate.get("scout_score"),
                },
                "learning_context": build_learning_context(),
            },
            default=str,
        )
        raw = self._call(system, user, timeout=35)
        parsed = _extract_json_object(raw)
        if not parsed:
            return {
                "decision": "SKIP",
                "confidence": 0.0,
                "reasoning": "LLM unavailable or malformed response",
                "llm_available": False,
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
            }

        decision = str(parsed.get("decision") or "SKIP").upper()
        if decision not in {"BUY", "SKIP"}:
            decision = "SKIP"
        conf = parsed.get("confidence")
        try:
            conf_f = max(0.0, min(1.0, float(conf)))
        except Exception:
            conf_f = 0.0
        try:
            mult = float(parsed.get("position_size_multiplier", 1.0))
            mult = max(0.8, min(1.2, mult))
        except Exception:
            mult = 1.0
        out = {
            "decision": decision,
            "confidence": conf_f,
            "reasoning": str(parsed.get("reasoning") or ""),
            "key_factors": parsed.get("key_factors") if isinstance(parsed.get("key_factors"), list) else [],
            "risks": parsed.get("risks") if isinstance(parsed.get("risks"), list) else [],
            "expected_outcome": str(parsed.get("expected_outcome") or ""),
            "learning_hypothesis": str(parsed.get("learning_hypothesis") or ""),
            "position_size_multiplier": mult,
            "llm_available": True,
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
        }
        self._append_reasoning(out)
        return out

    def evaluate_exit(self, position: dict[str, Any]) -> dict[str, Any]:
        symbol = str(position.get("ticker") or "").upper()
        system = (
            "You are managing an open position. Return ONLY JSON with keys: "
            "decision (HOLD/EXIT), confidence (0..1), reasoning, urgency (LOW/MEDIUM/HIGH)."
        )
        user = json.dumps(
            {
                "symbol": symbol,
                "position": {
                    "entry_price": position.get("entry_price"),
                    "current_price": position.get("current_price"),
                    "pnl_pct": position.get("pnl_pct"),
                    "days_held": position.get("days_held"),
                    "qty": position.get("qty") or position.get("shares"),
                },
                "note": "Judge this position on its own merits (paper trading). Past trades are irrelevant.",
            },
            default=str,
        )
        raw = self._call(system, user, timeout=30)
        parsed = _extract_json_object(raw)
        if not parsed:
            return {
                "decision": "HOLD",
                "confidence": 0.0,
                "reasoning": "LLM unavailable or malformed response",
                "urgency": "LOW",
                "llm_available": False,
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
            }
        decision = str(parsed.get("decision") or "HOLD").upper()
        if decision not in {"HOLD", "EXIT"}:
            decision = "HOLD"
        try:
            conf_f = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
        except Exception:
            conf_f = 0.0
        out = {
            "decision": decision,
            "confidence": conf_f,
            "reasoning": str(parsed.get("reasoning") or ""),
            "urgency": str(parsed.get("urgency") or "LOW").upper(),
            "llm_available": True,
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
        }
        self._append_reasoning(out)
        return out

    def discover_patterns(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        system = (
            "Analyze trade history and return ONLY JSON with keys: patterns (array), insights (array), recommendations (array)."
        )
        user = json.dumps({"trade_summary": self._summarize_trades(trades)}, default=str)
        parsed = _extract_json_object(self._call(system, user, timeout=40))
        if not parsed:
            return {"patterns": [], "insights": [], "recommendations": []}
        return {
            "patterns": parsed.get("patterns") if isinstance(parsed.get("patterns"), list) else [],
            "insights": parsed.get("insights") if isinstance(parsed.get("insights"), list) else [],
            "recommendations": parsed.get("recommendations") if isinstance(parsed.get("recommendations"), list) else [],
        }

    def generate_new_strategy(self, performance_data: dict[str, Any]) -> dict[str, Any] | None:
        system = (
            "Design a practical strategy and return ONLY JSON with keys: strategy_name, hypothesis, "
            "entry_rules (array), exit_rules (array), risk_management, expected_sharpe."
        )
        parsed = _extract_json_object(self._call(system, json.dumps(performance_data, default=str), timeout=45))
        if not parsed:
            return None
        return parsed

    def _load_recent_trades(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        path = DATA_DIR / "decisions_log.jsonl"
        if not path.exists():
            return rows
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    d = rec.get("decision") if isinstance(rec.get("decision"), dict) else rec
                    o = rec.get("outcome") if isinstance(rec.get("outcome"), dict) else {}
                    if str(d.get("action") or "").upper() != "BUY":
                        continue
                    rows.append(
                        {
                            "symbol": d.get("ticker"),
                            "win": float(o.get("pnl_pct") or 0.0) > 0,
                            "pnl": float(o.get("pnl_pct") or 0.0),
                            "strategy": d.get("signal_mode") or d.get("strategy_id") or "unknown",
                        }
                    )
        except Exception:
            return []
        return rows[-200:]

    def _recent_performance_summary(self) -> dict[str, Any]:
        t = self.recent_trades
        if not t:
            return {"total_trades": 0}
        wins = sum(1 for x in t if x.get("win"))
        losses = len(t) - wins
        avg_pnl = sum(float(x.get("pnl") or 0.0) for x in t) / max(1, len(t))
        return {
            "total_trades": len(t),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / max(1, len(t)), 4),
            "avg_pnl_pct": round(avg_pnl, 4),
            "recent_symbols": [x.get("symbol") for x in t[-5:]],
        }

    def _summarize_trades(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        if not trades:
            trades = self.recent_trades
        if not trades:
            return {"total": 0}
        wins = sum(1 for t in trades if bool(t.get("win")))
        total = len(trades)
        return {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / max(1, total), 4),
            "avg_pnl": round(sum(float(t.get("pnl") or 0.0) for t in trades) / max(1, total), 4),
            "strategies": self._group_by(trades, "strategy"),
            "sample_trades": trades[-10:],
        }

    def _group_by(self, trades: list[dict[str, Any]], key: str) -> dict[str, Any]:
        out: dict[str, dict[str, Any]] = {}
        for t in trades:
            k = str(t.get(key) or "unknown")
            rec = out.setdefault(k, {"wins": 0, "losses": 0, "total_pnl": 0.0})
            if bool(t.get("win")):
                rec["wins"] += 1
            else:
                rec["losses"] += 1
            rec["total_pnl"] += float(t.get("pnl") or 0.0)
        for rec in out.values():
            n = rec["wins"] + rec["losses"]
            rec["win_rate"] = round(rec["wins"] / max(1, n), 4)
        return out

    def _append_reasoning(self, decision: dict[str, Any]) -> None:
        try:
            with open(REASONING_HISTORY, "a", encoding="utf-8") as f:
                f.write(json.dumps(decision) + "\n")
        except Exception as e:
            logger.warning("Could not write llm reasoning history: %s", e)

