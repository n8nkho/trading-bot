#!/usr/bin/env python3
"""Backtesting harness for retrospective stack evaluation."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import pstdev
from typing import Any

from agents.critique_loop import evaluate_with_critique
from utils.atomic_json import read_json, write_json_atomic
from utils.fortress_logger import append_log

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_TRADES = _DATA / "trade_history.json"
_REFLECT = _DATA / "reflection_log.json"
_RESULTS = _DATA / "backtest_results.json"
_ENABLED = os.getenv("FORTRESS_BACKTEST_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _iso_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


class BacktestAgent:
    def _screen_l2_score(self, trade: dict[str, Any]) -> float:
        ind = trade.get("indicators", {}) if isinstance(trade.get("indicators"), dict) else {}
        rsi = float(ind.get("rsi", 50) or 50)
        volume_ratio = float(ind.get("volume_ratio", 1.0) or 1.0)
        macd = str(ind.get("macd", "")).lower()
        trend = float(ind.get("trend_score", 50) or 50)
        score = 0.0
        score += 0.25 * max(0.0, min(100.0, trend))
        score += 0.2 * max(0.0, min(100.0, (volume_ratio - 0.6) / 1.4 * 100.0))
        score += 0.2 * (80.0 if macd in {"bullish", "buy", "up"} else 45.0)
        score += 0.15 * max(0.0, min(100.0, (55.0 - rsi) / 30.0 * 100.0))
        score += 0.1 * 70.0
        score += 0.1 * 100.0
        return score

    def _sharpe_proxy(self, pnl: list[float]) -> float:
        if not pnl:
            return 0.0
        mean = sum(pnl) / len(pnl)
        std = pstdev(pnl) if len(pnl) > 1 else 0.0
        if std <= 1e-9:
            return 0.0
        return mean / std

    def run(self, start_date: str | None = None, end_date: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        trades_doc = read_json(_TRADES, default={"trades": []})
        trades = trades_doc.get("trades", []) if isinstance(trades_doc, dict) else []
        if not isinstance(trades, list):
            trades = []

        start_dt = _iso_date(start_date + "T00:00:00+00:00") if start_date else None
        end_dt = _iso_date(end_date + "T23:59:59+00:00") if end_date else None
        filt: list[dict[str, Any]] = []
        for t in trades:
            ct = _iso_date(str(t.get("closed_at") or t.get("exit_time") or ""))
            if start_dt and ct and ct < start_dt:
                continue
            if end_dt and ct and ct > end_dt:
                continue
            filt.append(t)

        orig_pnl = [float(t.get("pnl_pct_fraction", 0.0) or 0.0) for t in filt]
        bt_pnl: list[float] = []
        rejected_pnl: list[float] = []
        modified = 0
        agree = 0
        tier_counter = Counter()
        missed_opp = []
        correct_rej = []

        for t in filt:
            symbol = str(t.get("ticker") or t.get("symbol") or "")
            tech = self._screen_l2_score(t)
            passed_screen = tech >= 65.0
            signal = {
                "symbol": symbol,
                "direction": "BUY",
                "confidence": min(1.0, max(0.0, tech / 100.0)),
                "tech_score": tech,
                "indicators": t.get("indicators") or {},
            }
            crit = evaluate_with_critique(signal, {"symbol": symbol, "side": "buy"}, dry_run=True)
            verdict = crit.get("verdict", "REJECT")
            pnl = float(t.get("pnl_pct_fraction", 0.0) or 0.0)
            orig_verdict = str(t.get("critique_verdict") or "UNKNOWN").upper()
            if verdict == orig_verdict:
                agree += 1
            if verdict == "MODIFY":
                modified += 1
            if (not passed_screen) or verdict == "REJECT":
                rejected_pnl.append(pnl)
                if pnl > 0:
                    missed_opp.append({"symbol": symbol, "date": t.get("closed_at"), "pnl": pnl})
                elif pnl < 0:
                    correct_rej.append({"symbol": symbol, "date": t.get("closed_at"), "pnl": pnl})
                continue
            mult = 0.5 if verdict == "MODIFY" else 1.0
            bt_pnl.append(pnl * mult)
            tier = str(t.get("exit_tier") or t.get("tier") or "NA")
            tier_counter[tier] += 1

        def _avg(x: list[float]) -> float:
            return (sum(x) / len(x)) if x else 0.0

        ow = (sum(1 for x in orig_pnl if x > 0) / len(orig_pnl) * 100.0) if orig_pnl else 0.0
        bw = (sum(1 for x in bt_pnl if x > 0) / len(bt_pnl) * 100.0) if bt_pnl else 0.0
        avg_ref = 0.0
        ref = read_json(_REFLECT, default={"entries": [], "records": []})
        rows = []
        if isinstance(ref, dict):
            rows = ref.get("records") or ref.get("entries") or []
        scores = []
        for r in rows if isinstance(rows, list) else []:
            try:
                scores.append(float(r.get("score")))
            except Exception:
                pass
        if scores:
            avg_ref = sum(scores) / len(scores)

        date_range = f"{start_date or 'ALL'}..{end_date or 'ALL'}"
        report_lines = [
            "=" * 48,
            f"FORTRESS BACKTEST REPORT — {date_range}",
            "=" * 48,
            f"Total trades analyzed: {len(filt)}",
            "",
            "ORIGINAL PERFORMANCE:",
            f"  Win rate: {ow:.2f}%",
            f"  Avg P&L per trade: {_avg(orig_pnl)*100:.2f}%",
            f"  Best exit tier: {(tier_counter.most_common(1)[0][0] if tier_counter else 'N/A')}",
            "",
            "BACKTESTED (current stack) PERFORMANCE:",
            f"  Win rate: {bw:.2f}%",
            f"  Avg P&L per trade: {_avg(bt_pnl)*100:.2f}%",
            f"  Trades that would have been rejected: {len(rejected_pnl)} (avoided P&L: {sum(rejected_pnl)*100:.2f}%)",
            f"  Trades that would have been modified (50% size): {modified}",
            "",
            "IMPROVEMENT DELTA:",
            f"  Win rate change: {(bw-ow):+.2f}%",
            f"  P&L change: {((_avg(bt_pnl)-_avg(orig_pnl))*100):+.2f}%",
            "",
            "CRITIQUE QUALITY:",
            f"  Agreement rate: {(agree/len(filt)*100.0 if filt else 0.0):.2f}%",
            f"  Avg reflection score: {avg_ref:.2f}/10",
        ]
        for ln in report_lines:
            append_log(f"backtest_{datetime.now().strftime('%Y%m%d')}.log", ln)

        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date_range": {"start": start_date, "end": end_date},
            "total_trades": len(filt),
            "original": {"win_rate_pct": ow, "avg_pnl_pct": _avg(orig_pnl) * 100.0, "sharpe_proxy": self._sharpe_proxy(orig_pnl)},
            "backtested": {
                "win_rate_pct": bw,
                "avg_pnl_pct": _avg(bt_pnl) * 100.0,
                "sharpe_proxy": self._sharpe_proxy(bt_pnl),
                "rejected_count": len(rejected_pnl),
                "modified_count": modified,
            },
            "delta": {"win_rate_pct": bw - ow, "avg_pnl_pct": (_avg(bt_pnl) - _avg(orig_pnl)) * 100.0},
            "critique_agreement_rate_pct": (agree / len(filt) * 100.0 if filt else 0.0),
            "avg_reflection_score": avg_ref,
            "top_missed_opportunities": sorted(missed_opp, key=lambda x: -x["pnl"])[:5],
            "top_correct_rejections": sorted(correct_rej, key=lambda x: x["pnl"])[:5],
            "dry_run": dry_run,
        }
        if not dry_run and _ENABLED:
            doc = read_json(_RESULTS, default={"runs": []})
            if not isinstance(doc, dict) or not isinstance(doc.get("runs"), list):
                doc = {"runs": []}
            doc["runs"].append(out)
            write_json_atomic(_RESULTS, doc)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fortress backtest agent")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()
    out = BacktestAgent().run(start_date=args.start, end_date=args.end, dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
