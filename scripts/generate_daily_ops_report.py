#!/usr/bin/env python3
"""
Build a daily ops bundle under reports/ops_daily/ for operator review + AI-assisted analysis.

Run on the Oracle VM (where data/ and logs/ exist), then pull to Mac with:
  ./scripts/sync_pull_from_oracle.sh ubuntu@HOST

Uses only stdlib + local JSON/JSONL files — no Flask, no API keys in output.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl_all(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.is_file():
        return out
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def _tail_lines(path: Path, max_lines: int) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def _summarize_pnl_ledger(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {"count": 0, "wins": 0, "losses": 0, "realized_pnl": 0.0, "by_ticker": defaultdict(float)}
    by_day: dict[str, dict[str, float]] = defaultdict(lambda: {"pnl": 0.0, "count": 0})
    for rec in rows:
        pnl = _safe_float(rec.get("pnl"))
        if pnl is None:
            continue
        summary["count"] += 1
        summary["realized_pnl"] += pnl
        if pnl > 0:
            summary["wins"] += 1
        elif pnl < 0:
            summary["losses"] += 1
        t = str(rec.get("ticker") or "?")
        summary["by_ticker"][t] += pnl
        ts = str(rec.get("timestamp") or "")[:10]
        if ts and len(ts) >= 10:
            day = ts[:10]
            by_day[day]["pnl"] += pnl
            by_day[day]["count"] += 1
    summary["realized_pnl"] = round(summary["realized_pnl"], 2)
    summary["by_ticker"] = dict(sorted(summary["by_ticker"].items(), key=lambda x: abs(x[1]), reverse=True)[:25])
    summary["by_day"] = dict(sorted(by_day.items(), reverse=True)[:14])
    return summary


def _last_n_ledger_rows(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    if len(rows) <= n:
        return rows
    return rows[-n:]


def build_report(*, utc_day: str | None, log_tail: int, ledger_tail: int) -> dict[str, Any]:
    root = _root()
    data = root / "data"
    logs = root / "logs"

    now = datetime.now(timezone.utc)
    day = utc_day or now.strftime("%Y-%m-%d")

    ledger_path = data / "pnl_ledger.jsonl"
    ledger_rows = _read_jsonl_all(ledger_path)
    ledger_summary = _summarize_pnl_ledger(ledger_rows)

    report: dict[str, Any] = {
        "report_version": 1,
        "generated_at_utc": now.isoformat(),
        "report_day_utc": day,
        "paths": {
            "repo_root": str(root),
            "pnl_ledger": str(ledger_path),
            "last_screening_meta": str(data / "last_screening_meta.json"),
        },
        "pnl_ledger_summary": ledger_summary,
        "pnl_ledger_last_entries": _last_n_ledger_rows(ledger_rows, ledger_tail),
        "last_screening_meta": _read_json(data / "last_screening_meta.json"),
        "log_tails": {
            "orchestrator.log": _tail_lines(logs / "orchestrator.log", log_tail),
            "dashboard_systemd.log": _tail_lines(logs / "dashboard_systemd.log", log_tail),
            "fortress.log": _tail_lines(logs / "fortress.log", log_tail),
            "fortress_dashboard.log": _tail_lines(logs / "fortress_dashboard.log", log_tail),
        },
        "notes": [
            "Sanitize before sharing publicly (tickers/PnL are business-sensitive).",
            "Pull to Mac: ./scripts/sync_pull_from_oracle.sh ubuntu@ORACLE_IP",
            "Ask Cursor: paste this JSON or the .md summary + your question.",
        ],
    }
    return report


def _markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Daily ops report — {report.get('report_day_utc')}")
    lines.append("")
    lines.append(f"- **Generated (UTC):** `{report.get('generated_at_utc')}`")
    s = report.get("pnl_ledger_summary") or {}
    lines.append(f"- **Ledger trades:** {s.get('count', 0)}")
    lines.append(f"- **Realized PnL (all ledger rows):** `{s.get('realized_pnl', 0)}`")
    lines.append(f"- **Wins / losses:** {s.get('wins', 0)} / {s.get('losses', 0)}")
    lines.append("")
    meta = report.get("last_screening_meta") or {}
    if meta:
        lines.append("## Last screening meta (snapshot)")
        lines.append("")
        lines.append(f"- **strict_mode:** `{meta.get('strict_mode')}`")
        lines.append(f"- **strict_mode_reason:** `{meta.get('strict_mode_reason', '')}`")
        lines.append(f"- **candidates_found:** `{meta.get('candidates_found')}` **approved:** `{meta.get('approved')}`")
        lines.append(f"- **finished_at:** `{meta.get('screening_finished_at', meta.get('time', ''))}`")
        lines.append("")
    by_day = s.get("by_day") or {}
    if by_day:
        lines.append("## PnL by day (from ledger timestamps, last 14 keys)")
        lines.append("")
        for d, v in list(by_day.items())[:14]:
            lines.append(f"- **{d}:** pnl `{v.get('pnl', 0):.2f}` ({v.get('count', 0)} fills)")
        lines.append("")
    tickers = s.get("by_ticker") or {}
    if tickers:
        lines.append("## Top tickers by |realized PnL|")
        lines.append("")
        for t, p in list(tickers.items())[:15]:
            lines.append(f"- **{t}:** `{p:.2f}`")
        lines.append("")
    lines.append("## Recent ledger rows (see JSON for full tail)")
    lines.append("")
    for row in (report.get("pnl_ledger_last_entries") or [])[-8:]:
        lines.append(
            f"- `{row.get('timestamp')}` **{row.get('ticker')}** pnl `{row.get('pnl')}` "
            f"type `{row.get('type')}` order_id `{row.get('order_id')}`"
        )
    lines.append("")
    lines.append("## Log tails (truncated)")
    lines.append("")
    for name, body in (report.get("log_tails") or {}).items():
        if not (body or "").strip():
            continue
        lines.append(f"### {name}")
        lines.append("")
        lines.append("```")
        lines.append(body.strip()[-8000:])  # cap markdown size
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Write reports/ops_daily/* for sync + AI review.")
    ap.add_argument("--utc-day", help="Report label YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--log-tail", type=int, default=120, help="Lines per log file")
    ap.add_argument("--ledger-tail", type=int, default=80, help="Last N pnl ledger rows in JSON")
    ap.add_argument("--stdout-json", action="store_true", help="Print JSON to stdout only (no files)")
    args = ap.parse_args()

    report = build_report(utc_day=args.utc_day, log_tail=args.log_tail, ledger_tail=args.ledger_tail)
    root = _root()
    out_dir = root / "reports" / "ops_daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    day = report["report_day_utc"]
    jpath = out_dir / f"{day}.json"
    mpath = out_dir / f"{day}.md"

    if args.stdout_json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    jpath.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    mpath.write_text(_markdown(report), encoding="utf-8")
    # Stable names for “open LATEST” / AI review (docs/DAILY_OPS_REVIEW.md)
    (out_dir / "LATEST.json").write_text(jpath.read_text(encoding="utf-8"), encoding="utf-8")
    (out_dir / "LATEST.md").write_text(mpath.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[daily_ops_report] wrote {jpath}")
    print(f"[daily_ops_report] wrote {mpath}")
    print(f"[daily_ops_report] wrote {out_dir / 'LATEST.json'}")
    print(f"[daily_ops_report] wrote {out_dir / 'LATEST.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
