"""
Outbound operator alerts (Slack-compatible webhooks, generic JSON POST).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def send_operator_alert(event_type: str, payload: dict[str, Any] | None = None) -> bool:
    url = (os.environ.get("FORTRESS_ALERT_WEBHOOK_URL") or "").strip()
    if not url:
        return False
    body = {
        "event_type": event_type,
        "payload": payload or {},
    }
    # Slack incoming webhook expects "text"; include both.
    slack_text = f"[Fortress] {event_type}: {json.dumps(payload or {}, default=str)[:1500]}"
    try:
        data = json.dumps({"text": slack_text, **body}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= getattr(resp, "status", resp.getcode()) < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False
