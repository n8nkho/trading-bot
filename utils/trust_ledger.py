import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from utils.market_calendar import is_us_equity_rth_open, session_label


LEDGER_PATH = Path("data") / "trust_ledger.jsonl"
_MAX_LEDGER_SCAN = 12000


def _sha256_of_last_stored_line(path: Path) -> str:
    """Hash of the previous JSON line bytes (tamper-evidence chain). Empty file -> ''."""
    if not path.exists():
        return ""
    last = b""
    try:
        with open(path, "rb") as f:
            for raw in f:
                s = raw.rstrip(b"\r\n")
                if s:
                    last = s
    except Exception:
        return ""
    if not last:
        return ""
    return hashlib.sha256(last).hexdigest()


def append_trust_event(event_type: str, payload: dict) -> None:
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        prev = _sha256_of_last_stored_line(LEDGER_PATH)
        row = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "payload": payload or {},
            "chain_prev_sha256": prev,
        }
        with open(LEDGER_PATH, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        # Trust ledger must not break trading flow.
        pass


def read_recent_trust_events(limit: int = 100) -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    rows = []
    try:
        with open(LEDGER_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return rows[-max(1, int(limit)):]


def _read_trust_rows_for_scan(max_lines: int = _MAX_LEDGER_SCAN) -> list[dict]:
    """Scan recent ledger lines (bounded) to resolve run_id → terminal event."""
    if not LEDGER_PATH.exists():
        return []
    rows: list[dict] = []
    try:
        with open(LEDGER_PATH, "r") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return rows


def _age_minutes(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return (datetime.now(dt.tzinfo) - dt).total_seconds() / 60.0
    except Exception:
        return None


def _build_screening_run_terminations(rows: list[dict]) -> dict[str, dict]:
    """run_id -> {terminal: 'completed'|'failed'|None}."""
    state: dict[str, dict] = {}
    for ev in sorted(rows, key=lambda x: x.get("timestamp") or ""):
        rid = (ev.get("payload") or {}).get("run_id")
        if not rid:
            continue
        et = ev.get("event_type")
        st = state.setdefault(rid, {"terminal": None})
        if et == "screening_completed":
            st["terminal"] = "completed"
        elif et == "screening_failed":
            st["terminal"] = "failed"
    return state


def enrich_trust_ledger_items(items: list[dict]) -> list[dict]:
    """
    Add context for screening_started so it is not read as 'still running' when
    the matching completed/failed event exists (possibly outside the UI window)
    or when US markets are closed.
    """
    scan_rows = _read_trust_rows_for_scan()
    term = _build_screening_run_terminations(scan_rows)
    rth = is_us_equity_rth_open()
    out: list[dict] = []
    for ev in items:
        if ev.get("event_type") != "screening_started":
            out.append(ev)
            continue
        e = {**ev}
        rid = (ev.get("payload") or {}).get("run_id")
        terminal = (term.get(rid) or {}).get("terminal") if rid else None
        age = _age_minutes(ev.get("timestamp"))
        if terminal == "completed":
            e["screening_ledger_status"] = "finished"
            e["screening_ledger_note"] = "Run finished — see screening_completed for this run_id."
        elif terminal == "failed":
            e["screening_ledger_status"] = "failed"
            e["screening_ledger_note"] = "Run ended with error — see screening_failed for this run_id."
        elif not rth:
            e["screening_ledger_status"] = "after_hours"
            sl = session_label()
            if sl == "closed_holiday":
                e["screening_ledger_note"] = "NYSE holiday / full closure — screening not expected in progress."
            elif sl == "closed_weekend":
                e["screening_ledger_note"] = "Weekend — screening not expected in progress."
            else:
                e["screening_ledger_note"] = "Outside regular hours — screening not expected in progress."
        elif age is not None and age > 180:
            e["screening_ledger_status"] = "stale"
            e["screening_ledger_note"] = "No terminal event in ledger for this run_id — check orchestrator.log (crash, kill, or events aged out)."
        else:
            e["screening_ledger_status"] = "maybe_running"
            e["screening_ledger_note"] = "During market hours — may still be running if no completion logged yet."
        out.append(e)
    return out

