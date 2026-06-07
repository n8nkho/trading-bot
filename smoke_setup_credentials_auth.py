#!/usr/bin/env python3
"""Smoke: setup credential writes are first-run only and single-line safe."""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import types
from pathlib import Path


def _basic_auth(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _install_import_stubs() -> None:
    """Keep this smoke focused on setup auth instead of optional analytics deps."""
    if "utils.simple_daily_backtest" not in sys.modules:
        mod = types.ModuleType("utils.simple_daily_backtest")
        mod.read_backtest_snapshot = lambda *args, **kwargs: {}
        mod.run_daily_momentum_backtest = lambda *args, **kwargs: {"ok": True}
        sys.modules["utils.simple_daily_backtest"] = mod


def main() -> int:
    _install_import_stubs()
    import dashboard.command_center as cc

    old_env_file = cc.ENV_FILE
    old_setup_file = cc.SETUP_COMPLETE_FILE
    saved_env = {
        "FORTRESS_DASHBOARD_USER": os.environ.get("FORTRESS_DASHBOARD_USER"),
        "FORTRESS_DASHBOARD_PASS": os.environ.get("FORTRESS_DASHBOARD_PASS"),
        "FORTRESS_OPERATOR_TOKEN": os.environ.get("FORTRESS_OPERATOR_TOKEN"),
    }

    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cc.ENV_FILE = tmp / ".env"
            cc.SETUP_COMPLETE_FILE = tmp / "setup_complete"
            for key in saved_env:
                os.environ.pop(key, None)

            client = cc.app.test_client()
            first_key = "PK" + ("A" * 16)
            first_secret = "SK" + ("B" * 24)
            resp = client.post(
                "/api/setup/save_keys",
                json={"api_key": first_key, "secret_key": first_secret},
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)
            text = cc.ENV_FILE.read_text()
            assert f"ALPACA_API_KEY={first_key}" in text
            assert f"ALPACA_SECRET_KEY={first_secret}" in text

            cc.ENV_FILE.unlink()
            injected = "PK" + ("C" * 12) + "\nFORTRESS_LICENSE_TIER=master"
            resp = client.post(
                "/api/setup/save_keys",
                json={"api_key": injected, "secret_key": "SK" + ("D" * 24)},
            )
            assert resp.status_code == 400, resp.get_data(as_text=True)
            assert "single line" in resp.get_json()["error"]
            assert not cc.ENV_FILE.exists(), "rejected injection should not write .env"

            cc.ENV_FILE.write_text(
                "ALPACA_API_KEY=PK_EXISTING_REAL\n"
                "ALPACA_SECRET_KEY=SK_EXISTING_REAL_SECRET\n"
            )
            resp = client.post(
                "/api/setup/save_keys",
                json={"api_key": "PK" + ("E" * 16), "secret_key": "SK" + ("F" * 24)},
            )
            assert resp.status_code == 403, resp.get_data(as_text=True)
            assert "PK_EXISTING_REAL" in cc.ENV_FILE.read_text()

            resp = client.post("/api/setup/test_connection")
            assert resp.status_code == 403, resp.get_data(as_text=True)

            os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
            os.environ["FORTRESS_DASHBOARD_PASS"] = "change-me"
            authed_key = "PK" + ("G" * 16)
            authed_secret = "SK" + ("H" * 24)
            resp = client.post(
                "/api/setup/save_keys",
                headers=_basic_auth("operator", "change-me"),
                json={"api_key": authed_key, "secret_key": authed_secret},
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)
            text = cc.ENV_FILE.read_text()
            assert f"ALPACA_API_KEY={authed_key}" in text
            assert f"ALPACA_SECRET_KEY={authed_secret}" in text

        print("[OK] smoke_setup_credentials_auth")
        return 0
    finally:
        cc.ENV_FILE = old_env_file
        cc.SETUP_COMPLETE_FILE = old_setup_file
        for key, val in saved_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


if __name__ == "__main__":
    raise SystemExit(main())
