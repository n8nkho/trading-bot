#!/usr/bin/env python3
"""
Smoke: setup credential endpoints allow first-run setup but block post-setup
unauthenticated key overwrite.
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path


def _basic_auth(user: str, password: str) -> dict[str, str]:
    raw = f"{user}:{password}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def _post_save(client, api_key: str, secret_key: str, headers: dict[str, str] | None = None):
    return client.post(
        "/api/setup/save_keys",
        json={"api_key": api_key, "secret_key": secret_key},
        headers=headers or {},
    )


def main() -> int:
    import dashboard.command_center as cc

    old_data_dir = cc.DATA_DIR
    old_env_file = cc.ENV_FILE
    old_setup_file = cc.SETUP_COMPLETE_FILE
    env_keys = [
        "FORTRESS_DASHBOARD_USER",
        "FORTRESS_DASHBOARD_PASS",
        "FORTRESS_OPERATOR_TOKEN",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    ]
    old_env = {k: os.environ.get(k) for k in env_keys}

    with tempfile.TemporaryDirectory(prefix="fortress-setup-auth-") as td:
        tmp = Path(td)
        cc.DATA_DIR = tmp / "data"
        cc.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cc.ENV_FILE = tmp / ".env"
        cc.SETUP_COMPLETE_FILE = cc.DATA_DIR / "setup_complete"
        for k in env_keys:
            os.environ.pop(k, None)

        client = cc.app.test_client()

        first = _post_save(client, "PKTESTFIRST12345", "SKTESTFIRST12345")
        assert first.status_code == 200, first.get_data(as_text=True)
        assert "PKTESTFIRST12345" in cc.ENV_FILE.read_text(encoding="utf-8")

        blocked = _post_save(client, "PKTESTATTACK12345", "SKTESTATTACK12345")
        assert blocked.status_code == 403, blocked.get_data(as_text=True)
        assert "PKTESTATTACK12345" not in cc.ENV_FILE.read_text(encoding="utf-8")

        os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
        os.environ["FORTRESS_DASHBOARD_PASS"] = "secret-pass"
        authed = _post_save(
            client,
            "PKTESTROTATE12345",
            "SKTESTROTATE12345",
            headers=_basic_auth("operator", "secret-pass"),
        )
        assert authed.status_code == 200, authed.get_data(as_text=True)
        assert "PKTESTROTATE12345" in cc.ENV_FILE.read_text(encoding="utf-8")

    cc.DATA_DIR = old_data_dir
    cc.ENV_FILE = old_env_file
    cc.SETUP_COMPLETE_FILE = old_setup_file
    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    print("[OK] smoke_setup_api_auth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
