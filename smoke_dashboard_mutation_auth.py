#!/usr/bin/env python3
"""Smoke: sensitive dashboard mutation routes require auth after setup."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

import dashboard.command_center as cc
import utils.operator_halt as operator_halt
import utils.trust_ledger as trust_ledger


TEST_ENV = (
    "FORTRESS_DASHBOARD_USER",
    "FORTRESS_DASHBOARD_PASS",
    "FORTRESS_OPERATOR_TOKEN",
    "FORTRESS_ALERT_WEBHOOK_URL",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
)


def _clear_test_env() -> None:
    for key in TEST_ENV:
        os.environ.pop(key, None)


def _basic(user: str, password: str) -> dict[str, str]:
    raw = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {raw}"}


def main() -> int:
    old_env_file = cc.ENV_FILE
    old_setup_file = cc.SETUP_COMPLETE_FILE
    old_data_dir = cc.DATA_DIR
    old_halt_path = operator_halt.HALT_PATH
    old_ledger_path = trust_ledger.LEDGER_PATH
    old_env = {key: os.environ.get(key) for key in TEST_ENV}
    try:
        with tempfile.TemporaryDirectory() as td_raw:
            td = Path(td_raw)
            cc.ENV_FILE = td / ".env"
            cc.DATA_DIR = td / "data"
            cc.DATA_DIR.mkdir()
            cc.SETUP_COMPLETE_FILE = cc.DATA_DIR / "setup_complete"
            operator_halt.HALT_PATH = cc.DATA_DIR / "operator_trading_halt.json"
            trust_ledger.LEDGER_PATH = cc.DATA_DIR / "trust_ledger.jsonl"
            cc.app.config["TESTING"] = True
            client = cc.app.test_client()

            _clear_test_env()
            cc.SETUP_COMPLETE_FILE.write_text("ok", encoding="utf-8")
            r = client.post("/api/setup/save_keys", json={"api_key": "A" * 20, "secret_key": "B" * 20})
            assert r.status_code == 403, r.get_data(as_text=True)
            assert not cc.ENV_FILE.exists(), "unauthenticated post-setup save_keys wrote .env"

            os.environ["FORTRESS_OPERATOR_TOKEN"] = "tok"
            r = client.post(
                "/api/setup/save_keys",
                headers={"X-Operator-Token": "tok"},
                json={"api_key": "A" * 12 + "\nINJECT=1", "secret_key": "B" * 20},
            )
            assert r.status_code == 400, r.get_data(as_text=True)
            assert not cc.ENV_FILE.exists(), "invalid env value wrote .env"

            r = client.post(
                "/api/setup/save_keys",
                headers={"X-Operator-Token": "tok"},
                json={"api_key": "A" * 20, "secret_key": "B" * 20},
            )
            assert r.status_code == 200, r.get_data(as_text=True)
            assert "ALPACA_API_KEY=" + "A" * 20 in cc.ENV_FILE.read_text(encoding="utf-8")

            _clear_test_env()
            os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
            os.environ["FORTRESS_DASHBOARD_PASS"] = "secret"
            r = client.post(
                "/api/setup/save_keys",
                headers=_basic("operator", "secret"),
                json={"api_key": "C" * 20, "secret_key": "D" * 20},
            )
            assert r.status_code == 200, r.get_data(as_text=True)

            _clear_test_env()
            cc.SETUP_COMPLETE_FILE.unlink()
            cc.ENV_FILE.unlink()
            r = client.post("/api/setup/save_keys", json={"api_key": "E" * 20, "secret_key": "F" * 20})
            assert r.status_code == 200, r.get_data(as_text=True)
            assert cc.ENV_FILE.exists(), "first-run setup save should remain public"

            _clear_test_env()
            r = client.post("/api/operator/halt", json={"active": True, "reason": "smoke", "actor": "smoke"})
            assert r.status_code == 403, r.get_data(as_text=True)
            assert not operator_halt.HALT_PATH.exists(), "unauthenticated halt wrote halt file"

            os.environ["FORTRESS_OPERATOR_TOKEN"] = "tok"
            r = client.post(
                "/api/operator/halt",
                headers={"X-Operator-Token": "tok"},
                json={"active": True, "reason": "smoke", "actor": "smoke"},
            )
            assert r.status_code == 200, r.get_data(as_text=True)
            assert operator_halt.get_halt_state()["effective_halted"], "authorized halt did not take effect"

            _clear_test_env()
            os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
            os.environ["FORTRESS_DASHBOARD_PASS"] = "secret"
            os.environ["FORTRESS_OPERATOR_TOKEN"] = "tok"
            r = client.post(
                "/api/operator/halt",
                headers={"X-Operator-Token": "tok"},
                json={"active": False, "reason": "token", "actor": "smoke"},
            )
            assert r.status_code == 200, r.get_data(as_text=True)
    finally:
        cc.ENV_FILE = old_env_file
        cc.SETUP_COMPLETE_FILE = old_setup_file
        cc.DATA_DIR = old_data_dir
        operator_halt.HALT_PATH = old_halt_path
        trust_ledger.LEDGER_PATH = old_ledger_path
        _clear_test_env()
        for key, value in old_env.items():
            if value is not None:
                os.environ[key] = value

    print("[OK] smoke_dashboard_mutation_auth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
