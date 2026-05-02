#!/usr/bin/env python3
"""Smoke: completed setup cannot be overwritten through the public setup API."""
from __future__ import annotations

import tempfile
from pathlib import Path

from dashboard import command_center as cc


def main() -> int:
    old_env_file = cc.ENV_FILE
    old_setup_complete_file = cc.SETUP_COMPLETE_FILE
    old_data_dir = cc.DATA_DIR

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        env_file = tmp / ".env"
        data_dir = tmp / "data"
        setup_complete = data_dir / "setup_complete"
        env_text = (
            "ALPACA_API_KEY=ORIGINAL_PAPER_KEY_12345\n"
            "ALPACA_SECRET_KEY=ORIGINAL_PAPER_SECRET_12345\n"
        )
        env_file.write_text(env_text, encoding="utf-8")

        cc.ENV_FILE = env_file
        cc.DATA_DIR = data_dir
        cc.SETUP_COMPLETE_FILE = setup_complete
        try:
            with cc.app.test_client() as client:
                response = client.post(
                    "/api/setup/save_keys",
                    json={
                        "api_key": "ATTACKER_PAPER_KEY_12345",
                        "secret_key": "ATTACKER_PAPER_SECRET_12345",
                    },
                )

            assert response.status_code == 409, response.get_data(as_text=True)
            assert env_file.read_text(encoding="utf-8") == env_text
        finally:
            cc.ENV_FILE = old_env_file
            cc.SETUP_COMPLETE_FILE = old_setup_complete_file
            cc.DATA_DIR = old_data_dir

    print("[OK] smoke_setup_keys_lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
