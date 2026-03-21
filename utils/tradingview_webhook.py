"""
TradingView alert webhook: append-only JSONL queue for human-in-the-loop / downstream review.

POST /api/hooks/tradingview with optional ?secret=... when FORTRESS_TV_WEBHOOK_SECRET is set.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = _ROOT / "data" / "tradingview_signal_queue.jsonl"
_MAX_LINES = 8000
_MAX_BODY_CHARS = 12000


def _trim_queue_file() -> None:
    if not QUEUE_PATH.exists():
        return
    try:
        lines = QUEUE_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _MAX_LINES:
            return
        keep = lines[-(_MAX_LINES // 2) :]
        QUEUE_PATH.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except Exception:
        pass


def verify_webhook_secret(query_secret: str | None, header_secret: str | None) -> bool:
    expected = (os.environ.get("FORTRESS_TV_WEBHOOK_SECRET") or "").strip()
    if not expected:
        return True
    got = (query_secret or header_secret or "").strip()
    return got == expected


def _parse_body(raw: bytes, content_type: str) -> tuple[Any, str]:
    ct = (content_type or "").lower()
    text = raw.decode("utf-8", errors="replace")[:_MAX_BODY_CHARS]
    if "application/json" in ct or text.strip().startswith(("{", "[")):
        try:
            return json.loads(text), "json"
        except json.JSONDecodeError:
            pass
    return text, "text"


def _guess_ticker(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for k in ("ticker", "symbol", "sym", "t"):
            v = payload.get(k)
            if v and isinstance(v, str):
                s = v.strip().upper()
                if re.match(r"^[A-Z]{1,5}$", s):
                    return s
        # TradingView often sends {{ticker}} expanded in a string field
        for v in payload.values():
            if isinstance(v, str) and re.match(r"^[A-Z]{1,5}$", v.strip()):
                return v.strip().upper()
    if isinstance(payload, str):
        m = re.search(r"\b([A-Z]{1,5})\b", payload.upper())
        if m:
            return m.group(1)
    return None


def append_tradingview_event(
    *,
    raw_body: bytes,
    content_type: str,
    remote_addr: str | None,
    query_params: dict[str, str],
) -> dict[str, Any]:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    parsed, kind = _parse_body(raw_body, content_type)
    row: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "source": "tradingview",
        "content_type": content_type or "",
        "parse_kind": kind,
        "remote_addr": (remote_addr or "")[:64],
        "query_keys": sorted([k for k in query_params if k.lower() != "secret"])[:20],
        "ticker_guess": _guess_ticker(parsed),
        "payload": parsed if kind == "json" else {"text": parsed},
    }
    line = json.dumps(row, default=str) + "\n"
    with open(QUEUE_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    _trim_queue_file()
    return row


def read_recent_signals(limit: int = 40) -> list[dict[str, Any]]:
    if not QUEUE_PATH.exists():
        return []
    limit = max(1, min(int(limit), 200))
    rows: list[dict[str, Any]] = []
    try:
        with open(QUEUE_PATH, "r", encoding="utf-8") as f:
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
    return rows[-limit:]
