"""
Walk-forward style validation from realized P&L ledger (retail-friendly, not full backtest).
Splits closed-trade history into earlier vs later windows and compares averages.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

LEDGER = Path("data") / "pnl_ledger.jsonl"
OUT = Path("data") / "walk_forward_report.json"


def _load_ledger_rows() -> list[dict]:
    rows = []
    if not LEDGER.exists():
        return rows
    with open(LEDGER, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def compute_walk_forward_report() -> dict:
    rows = _load_ledger_rows()
    pnls = []
    for r in rows:
        try:
            pnls.append(float(r.get("pnl") or 0.0))
        except Exception:
            continue

    n = len(pnls)
    half = max(1, n // 2)
    early = pnls[:half]
    late = pnls[half:]

    def _avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    early_avg = _avg(early)
    late_avg = _avg(late)
    degradation = None
    if early_avg != 0:
        degradation = round((late_avg - early_avg) / abs(early_avg), 4)

    stable = True
    reason = "insufficient_trades"
    if n >= 14:
        reason = "evaluated"
        if degradation is not None and degradation < -0.4:
            stable = False
            reason = "later_window_weaker"

    return {
        "timestamp": datetime.now().isoformat(),
        "total_trades": n,
        "early_window_trades": len(early),
        "late_window_trades": len(late),
        "early_avg_pnl": early_avg,
        "late_avg_pnl": late_avg,
        "degradation_ratio": degradation,
        "stable": stable,
        "reason": reason,
    }


def write_report() -> dict:
    report = compute_walk_forward_report()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(report, f, indent=2)
    return report


def get_research_verdict() -> dict:
    """
    Operator-facing headline for dashboards (Phase C — research rigor surface).
    """
    r = compute_walk_forward_report()
    n = int(r.get("total_trades") or 0)
    stable = r.get("stable")
    reason = r.get("reason") or ""
    deg = r.get("degradation_ratio")
    if n < 14:
        headline = f"Walk-forward: need more closed trades (have {n}, need ≥14 for stability read)."
        verdict = "insufficient_data"
    elif stable is True:
        headline = "Walk-forward: late-window P&L consistent with early window (no strong degradation)."
        verdict = "stable"
    else:
        headline = "Walk-forward: late-window weaker than early — review strategy decay before sizing up."
        verdict = "unstable"
    return {
        "verdict": verdict,
        "headline": headline,
        "total_trades": n,
        "stable": stable,
        "reason": reason,
        "degradation_ratio": deg,
        "report_path": str(OUT),
        "timestamp": r.get("timestamp"),
    }


if __name__ == "__main__":
    print(json.dumps(write_report(), indent=2))
