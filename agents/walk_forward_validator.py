"""
Walk-forward style validation from realized P&L ledger (retail-friendly, not full backtest).

Splits closed-trade history into sequential windows and compares early vs late performance.
Diagnostics explain *where* degradation appears without changing pass criteria to game the gate.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

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


def _pnls_from_rows(rows: list[dict]) -> list[float]:
    pnls = []
    for r in rows:
        try:
            pnls.append(float(r.get("pnl") or 0.0))
        except Exception:
            continue
    return pnls


def _window_pnls(pnls: list[float], num_windows: int) -> list[list[float]]:
    """Split pnls into `num_windows` contiguous chunks (last chunk may be larger)."""
    if not pnls or num_windows < 1:
        return []
    n = len(pnls)
    base = n // num_windows
    rem = n % num_windows
    out: list[list[float]] = []
    idx = 0
    for w in range(num_windows):
        sz = base + (1 if w < rem else 0)
        if sz <= 0:
            continue
        out.append(pnls[idx : idx + sz])
        idx += sz
    return out


def _avg(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 6) if xs else 0.0


def _win_rate(xs: list[float]) -> float | None:
    if not xs:
        return None
    wins = sum(1 for x in xs if x > 0)
    return round(wins / len(xs), 4)


def _max_drawdown_cumulative(xs: list[float]) -> float:
    """Largest peak-to-trough drop on cumulative P&L path (negative or zero)."""
    cum = 0.0
    peak = 0.0
    worst = 0.0
    for x in xs:
        cum += x
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return round(worst, 4)


def _sharpe_like(xs: list[float]) -> float | None:
    """Unitless Sharpe-like ratio using per-trade P&L as `returns` (not annualized)."""
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    std = math.sqrt(var)
    if std < 1e-12:
        return None
    return round((m / std) * math.sqrt(len(xs)), 4)


def _diagnostic_hypotheses(
    *,
    windows_detail: list[dict[str, Any]],
    degradation_ratio: float | None,
    stable: bool,
) -> list[str]:
    """Heuristic hints — not causal proof; operators investigate."""
    hints: list[str] = []
    if not windows_detail:
        return hints
    counts = [int(w.get("n") or 0) for w in windows_detail]
    if counts and max(counts) - min(counts) >= max(3, len(windows_detail)):
        hints.append(
            "Uneven trades per window — sample sizes differ; compare avg_pnl only with caution."
        )
    avgs = [float(w.get("avg_pnl") or 0.0) for w in windows_detail]
    if len(avgs) >= 3 and avgs[-1] < min(avgs[:-1]):
        hints.append("Latest window has weakest avg_pnl — possible regime shift or fatigue of signal.")
    if degradation_ratio is not None and degradation_ratio < -0.4 and not stable:
        hints.append(
            "Late vs early aggregate degradation exceeds gate — review for overfitting to early luck "
            "or structural drift (liquidity, volatility, execution)."
        )
    # Data quality hint: zero variance windows
    for w in windows_detail:
        if int(w.get("n") or 0) >= 4 and w.get("sharpe_like") is None:
            hints.append(
                f"Window {w.get('index')} has near-zero variance — check ledger spikes or stale fills."
            )
            break
    return hints


def compute_walk_forward_report() -> dict[str, Any]:
    rows = _load_ledger_rows()
    pnls = _pnls_from_rows(rows)

    num_windows = max(2, int(os.getenv("FORTRESS_WF_NUM_WINDOWS", "4")))
    threshold_frac = float(os.getenv("FORTRESS_WF_DROP_THRESHOLD_FRAC", "0.5"))

    n = len(pnls)
    half = max(1, n // 2)
    early = pnls[:half]
    late = pnls[half:]

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

    windows_slices = _window_pnls(pnls, num_windows)
    windows_detail: list[dict[str, Any]] = []
    for i, chunk in enumerate(windows_slices, start=1):
        windows_detail.append(
            {
                "index": i,
                "n": len(chunk),
                "avg_pnl": _avg(chunk),
                "win_rate": _win_rate(chunk),
                "max_drawdown_cumulative": _max_drawdown_cumulative(chunk),
                "sharpe_like": _sharpe_like(chunk),
            }
        )

    first_weak_window: int | None = None
    benchmark_windows = windows_detail[: max(1, len(windows_detail) // 2)]
    bench_avg = (
        sum(float(w["avg_pnl"]) for w in benchmark_windows) / len(benchmark_windows)
        if benchmark_windows
        else None
    )
    floor = None
    if bench_avg is not None:
        if bench_avg > 0:
            floor = bench_avg * threshold_frac
        elif bench_avg < 0:
            floor = bench_avg * (1 + (1 - threshold_frac))

    if floor is not None and windows_detail:
        for w in windows_detail[len(benchmark_windows) :]:
            try:
                if float(w.get("avg_pnl") or 0.0) < floor:
                    first_weak_window = int(w["index"])
                    break
            except Exception:
                continue

    hypotheses = _diagnostic_hypotheses(
        windows_detail=windows_detail,
        degradation_ratio=degradation,
        stable=stable,
    )

    report = {
        "timestamp": datetime.now().isoformat(),
        "total_trades": n,
        "early_window_trades": len(early),
        "late_window_trades": len(late),
        "early_avg_pnl": early_avg,
        "late_avg_pnl": late_avg,
        "degradation_ratio": degradation,
        "stable": stable,
        "reason": reason,
        "num_windows": num_windows,
        "windows": windows_detail,
        "early_benchmark_avg_pnl": bench_avg,
        "performance_floor_vs_benchmark": floor,
        "threshold_frac_of_early_benchmark": threshold_frac,
        "first_underperforming_window": first_weak_window,
        "diagnostic_hypotheses": hypotheses,
        "notes": (
            "Gate uses legacy half-split degradation_ratio < -0.4 when n>=14; "
            "per-window metrics are diagnostic only. "
            "Sharpe-like uses per-trade P&L — interpret qualitatively."
        ),
    }
    return report


def write_report() -> dict[str, Any]:
    report = compute_walk_forward_report()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(report, f, indent=2)
    return report


def get_research_verdict() -> dict[str, Any]:
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
        "windows": r.get("windows"),
        "diagnostic_hypotheses": r.get("diagnostic_hypotheses"),
    }


if __name__ == "__main__":
    print(json.dumps(write_report(), indent=2))
