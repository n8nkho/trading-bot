#!/usr/bin/env python3
"""Smoke: setup key mutations are protected after setup and reject .env injection."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def main() -> int:
    old_env = {k: os.environ.get(k) for k in ("FORTRESS_DASHBOARD_USER", "FORTRESS_DASHBOARD_PASS", "FORTRESS_OPERATOR_TOKEN")}
    os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
    os.environ["FORTRESS_DASHBOARD_PASS"] = "secret-pass"
    os.environ.pop("FORTRESS_OPERATOR_TOKEN", None)

    try:
        from dashboard import command_center as dash

        dash.app.config["TESTING"] = True
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dash.DATA_DIR = tmp_path
            dash.ENV_FILE = tmp_path / ".env"
            dash.SETUP_COMPLETE_FILE = tmp_path / "setup_complete"
            dash.ENV_FILE.write_text(
                "ALPACA_API_KEY=EXISTINGKEY12345\nALPACA_SECRET_KEY=EXISTINGSECRET12345\n",
                encoding="utf-8",
            )

            client = dash.app.test_client()
            payload = {"api_key": "NEWKEY123456789", "secret_key": "NEWSECRET123456789"}
            unauth = client.post("/api/setup/save_keys", json=payload)
            assert unauth.status_code == 401, unauth.get_data(as_text=True)
            assert "NEWKEY" not in dash.ENV_FILE.read_text(encoding="utf-8")

            authed = client.post("/api/setup/save_keys", json=payload, headers=_basic("operator", "secret-pass"))
            assert authed.status_code == 200, authed.get_data(as_text=True)
            assert "ALPACA_API_KEY=NEWKEY123456789" in dash.ENV_FILE.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dash.DATA_DIR = tmp_path
            dash.ENV_FILE = tmp_path / ".env"
            dash.SETUP_COMPLETE_FILE = tmp_path / "setup_complete"

            client = dash.app.test_client()
            injected = client.post(
                "/api/setup/save_keys",
                json={"api_key": "VALIDKEY12345\nEVIL=1", "secret_key": "VALIDSECRET12345"},
            )
            assert injected.status_code == 400, injected.get_data(as_text=True)
            if dash.ENV_FILE.exists():
                assert "EVIL=1" not in dash.ENV_FILE.read_text(encoding="utf-8")
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("[OK] smoke_dashboard_mutation_auth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
