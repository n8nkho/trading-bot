"""
Classic pnl_ledger.jsonl health — detect stale canonical ledger for the Classic book only.

Classic orchestrator writes exits to data/pnl_ledger.jsonl. Fortress AI uses a separate Alpaca
account and its own ledger; Fortress activity must not be used to explain Classic staleness.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_CLASSIC_LEDGER = _ROOT / "data" / "pnl_ledger.jsonl"


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        s = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def classic_ledger_order_ids(path: Path | None = None) -> set[str]:
    p = path or _CLASSIC_LEDGER
    ids: set[str] = set()
    if not p.is_file():
        return ids
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        oid = row.get("order_id")
        if oid:
            ids.add(str(oid))
    return ids


def classic_ledger_last_exit_at(path: Path | None = None) -> datetime | None:
    p = path or _CLASSIC_LEDGER
    if not p.is_file():
        return None
    latest: datetime | None = None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("mirrored_from"):
            continue
        dt = _parse_ts(row.get("timestamp") or row.get("ts"))
        if dt and (latest is None or dt > latest):
            latest = dt
    return latest


def _broker_closed_sells_since(since: datetime) -> list[dict[str, Any]]:
    """Filled SELL orders from Classic Alpaca since `since` (best-effort)."""
    try:
        from dotenv import load_dotenv
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        load_dotenv(_ROOT / ".env")
        key = os.environ.get("ALPACA_API_KEY")
        sec = os.environ.get("ALPACA_SECRET_KEY")
        if not key or not sec:
            return []
        c = TradingClient(key, sec, paper=True)
        orders = c.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=100, nested=True))
        out: list[dict[str, Any]] = []
        for o in orders:
            if str(getattr(o, "side", "")).lower() != "sell":
                continue
            filled = getattr(o, "filled_qty", None)
            try:
                if filled is not None and float(filled) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            ts = _parse_ts(str(getattr(o, "filled_at", None) or getattr(o, "submitted_at", None) or ""))
            if ts is None or ts < since:
                continue
            out.append(
                {
                    "order_id": str(o.id),
                    "symbol": str(o.symbol),
                    "filled_at": ts.isoformat(),
                    "filled_qty": filled,
                    "filled_avg_price": getattr(o, "filled_avg_price", None),
                }
            )
        return out
    except Exception:
        return []


def audit_ledger_gap(*, stale_days: float = 3.0) -> dict[str, Any]:
    """
    Classic-only ledger staleness audit. Does not mutate files.
    """
    now = datetime.now(timezone.utc)
    classic_last = classic_ledger_last_exit_at()
    classic_age_days = (
        (now - classic_last).total_seconds() / 86400.0 if classic_last else None
    )

    broker_missing: list[dict[str, Any]] = []
    if classic_last:
        broker_missing = _broker_closed_sells_since(classic_last)
        known = classic_ledger_order_ids()
        broker_missing = [x for x in broker_missing if x.get("order_id") not in known]

    gap = bool(
        classic_age_days is not None and classic_age_days >= stale_days
    ) or bool(broker_missing)

    return {
        "classic_ledger_path": str(_CLASSIC_LEDGER),
        "classic_last_exit_at": classic_last.isoformat() if classic_last else None,
        "classic_age_days": round(classic_age_days, 2) if classic_age_days is not None else None,
        "broker_sells_missing_from_classic": len(broker_missing),
        "broker_missing_sample": broker_missing[:5],
        "ledger_gap_detected": gap,
        "explanation": (
            "Classic canonical data/pnl_ledger.jsonl is written only by the Classic orchestrator "
            "on the Classic Alpaca account. Fortress AI uses a separate account and ledger."
        ),
    }


def scan_classic_pnl_ledger_stale(*, stale_days: float = 3.0) -> list[dict[str, Any]]:
    audit = audit_ledger_gap(stale_days=stale_days)
    if not audit.get("ledger_gap_detected"):
        return []
    return [
        {
            "code": "classic_pnl_ledger_stale",
            "severity": "high",
            "component": "classic_fortress",
            "classic_age_days": audit.get("classic_age_days"),
            "broker_sells_missing": audit.get("broker_sells_missing_from_classic"),
            "recommendation": (
                "Canonical data/pnl_ledger.jsonl has no recent Classic orchestrator exits — "
                "drift/WF/fused-signal/ledger-health gates reading this file are blind. "
                "Investigate Classic exit path or backfill from Classic broker reconciliation."
            ),
            "si_action": "investigate_classic_ledger_staleness",
            "audit": audit,
        }
    ]
