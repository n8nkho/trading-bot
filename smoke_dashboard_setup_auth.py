#!/usr/bin/env python3
"""Smoke test: completed setup endpoints cannot be used to overwrite broker keys anonymously."""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
os.environ["FORTRESS_DASHBOARD_PASS"] = "correct-horse"

from dashboard import command_center as cc  # noqa: E402


def _basic_auth_header(user: str = "operator", password: str = "correct-horse") -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def main() -> int:
    old_env_file = cc.ENV_FILE
    old_setup_file = cc.SETUP_COMPLETE_FILE
    payload_a = {"api_key": "A" * 16, "secret_key": "S" * 16}
    payload_b = {"api_key": "B" * 16, "secret_key": "T" * 16}

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cc.ENV_FILE = tmp / ".env"
        cc.SETUP_COMPLETE_FILE = tmp / "setup_complete"
        client = cc.app.test_client()
        try:
            first = client.post("/api/setup/save_keys", json=payload_a)
            assert first.status_code == 200, first.get_data(as_text=True)
            assert "ALPACA_API_KEY=" + payload_a["api_key"] in cc.ENV_FILE.read_text()

            cc.SETUP_COMPLETE_FILE.write_text("ok", encoding="utf-8")
            before = cc.ENV_FILE.read_text()
            blocked = client.post("/api/setup/save_keys", json=payload_b)
            assert blocked.status_code == 403, blocked.get_data(as_text=True)
            assert cc.ENV_FILE.read_text() == before

            authed = client.post("/api/setup/save_keys", json=payload_b, headers=_basic_auth_header())
            assert authed.status_code == 200, authed.get_data(as_text=True)
            assert "ALPACA_API_KEY=" + payload_b["api_key"] in cc.ENV_FILE.read_text()

            blocked_test = client.post("/api/setup/test_connection")
            assert blocked_test.status_code == 403, blocked_test.get_data(as_text=True)
        finally:
            cc.ENV_FILE = old_env_file
            cc.SETUP_COMPLETE_FILE = old_setup_file

    print("smoke_dashboard_setup_auth: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
