#!/usr/bin/env python3
"""Smoke test: completed setup APIs cannot be used to overwrite Alpaca keys anonymously."""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from dashboard import command_center as cc


def _auth_header(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _post_keys(client, api_key: str = "PKTESTKEY12345", secret_key: str = "SKTESTSECRET12345", headers=None):
    return client.post(
        "/api/setup/save_keys",
        json={"api_key": api_key, "secret_key": secret_key},
        headers=headers or {},
    )


def main() -> int:
    old_env_file = cc.ENV_FILE
    old_setup_file = cc.SETUP_COMPLETE_FILE
    old_user = os.environ.get("FORTRESS_DASHBOARD_USER")
    old_pass = os.environ.get("FORTRESS_DASHBOARD_PASS")

    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            env_file = tmp / ".env"
            setup_file = tmp / "setup_complete"
            cc.ENV_FILE = env_file
            cc.SETUP_COMPLETE_FILE = setup_file
            os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
            os.environ["FORTRESS_DASHBOARD_PASS"] = "correct-horse"

            # Existing keys mean setup is already complete even if the marker file is absent.
            original = "ALPACA_API_KEY=PKEXISTING12345\nALPACA_SECRET_KEY=SKEXISTING12345\n"
            env_file.write_text(original, encoding="utf-8")

            client = cc.app.test_client()
            unauth = _post_keys(client, api_key="PKATTACKER12345", secret_key="SKATTACKER12345")
            assert unauth.status_code == 401, unauth.get_data(as_text=True)
            assert env_file.read_text(encoding="utf-8") == original

            authed = _post_keys(
                client,
                api_key="PKOPERATOR12345",
                secret_key="SKOPERATOR12345",
                headers=_auth_header("operator", "correct-horse"),
            )
            assert authed.status_code == 200, authed.get_data(as_text=True)
            updated = env_file.read_text(encoding="utf-8")
            assert "PKOPERATOR12345" in updated
            assert "SKOPERATOR12345" in updated

            # First-run onboarding remains public before any keys or setup marker exist.
            env_file.unlink()
            if setup_file.exists():
                setup_file.unlink()
            first_run = _post_keys(client, api_key="PKFIRSTRUN12345", secret_key="SKFIRSTRUN12345")
            assert first_run.status_code == 200, first_run.get_data(as_text=True)

        print("smoke_dashboard_setup_auth: PASS")
        return 0
    finally:
        cc.ENV_FILE = old_env_file
        cc.SETUP_COMPLETE_FILE = old_setup_file
        if old_user is None:
            os.environ.pop("FORTRESS_DASHBOARD_USER", None)
        else:
            os.environ["FORTRESS_DASHBOARD_USER"] = old_user
        if old_pass is None:
            os.environ.pop("FORTRESS_DASHBOARD_PASS", None)
        else:
            os.environ["FORTRESS_DASHBOARD_PASS"] = old_pass


if __name__ == "__main__":
    raise SystemExit(main())
