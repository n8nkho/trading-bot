#!/usr/bin/env python3
"""
Smoke: dashboard mutation endpoints are not anonymously writable after setup.
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import types
from pathlib import Path


def _module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, val in attrs.items():
        setattr(mod, key, val)
    sys.modules[name] = mod
    return mod


def _install_dashboard_import_stubs() -> None:
    agents_pkg = _module("agents")
    agents_pkg.__path__ = []
    _module("agents.drift_detector", analyze_drift=lambda *args, **kwargs: {})
    _module("utils.market_assets", require_market_assets=lambda *args, **kwargs: None)
    _module("utils.policy_profile", get_profile_bundle=lambda: {})
    _module(
        "utils.trust_ledger",
        append_trust_event=lambda *args, **kwargs: None,
        enrich_trust_ledger_items=lambda items: items,
        read_recent_trust_events=lambda *args, **kwargs: [],
    )
    _module(
        "utils.operator_halt",
        get_halt_state=lambda: {"file": {"active": False}, "effective_halted": False},
        set_trading_halt=lambda active, reason="", actor="dashboard": {"active": bool(active), "reason": reason, "actor": actor},
    )
    _module("utils.alerts", send_operator_alert=lambda *args, **kwargs: None)
    _module(
        "utils.simple_daily_backtest",
        read_backtest_snapshot=lambda: {},
        run_daily_momentum_backtest=lambda ticker: {"ticker": ticker},
    )
    _module("utils.run_registry", summarize_screening_runs=lambda *args, **kwargs: {})
    _module("utils.alpaca_env", is_alpaca_paper=lambda: True)


def _basic(user: str, password: str) -> dict[str, str]:
    raw = f"{user}:{password}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def main() -> int:
    keys = [
        "FORTRESS_DASHBOARD_USER",
        "FORTRESS_DASHBOARD_PASS",
        "FORTRESS_OPERATOR_TOKEN",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    ]
    env_snapshot = {key: os.environ.get(key) for key in keys}
    old_cwd = Path.cwd()
    try:
        for key in keys:
            os.environ.pop(key, None)
        _install_dashboard_import_stubs()
        import dashboard.command_center as cc

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cc.DATA_DIR = tmp / "data"
            cc.DATA_DIR.mkdir(parents=True, exist_ok=True)
            cc.SETUP_COMPLETE_FILE = cc.DATA_DIR / "setup_complete"
            cc.ENV_FILE = tmp / ".env"
            client = cc.app.test_client()

            first_run = client.post(
                "/api/setup/save_keys",
                json={"api_key": "AK" + "1" * 20, "secret_key": "SK" + "2" * 20},
            )
            assert first_run.status_code == 200, first_run.get_data(as_text=True)
            assert "ALPACA_API_KEY=AK" in cc.ENV_FILE.read_text(encoding="utf-8")

            blocked = client.post(
                "/api/setup/save_keys",
                json={"api_key": "AK" + "3" * 20, "secret_key": "SK" + "4" * 20},
            )
            assert blocked.status_code == 403, blocked.get_data(as_text=True)

            blocked_test = client.post("/api/setup/test_connection", json={})
            assert blocked_test.status_code == 403, blocked_test.get_data(as_text=True)

            os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
            os.environ["FORTRESS_DASHBOARD_PASS"] = "secret"
            injected = client.post(
                "/api/setup/save_keys",
                json={"api_key": "AK" + "5" * 20, "secret_key": "SK" + "6" * 10 + "\nEVIL=1"},
                headers=_basic("operator", "secret"),
            )
            assert injected.status_code == 400, injected.get_data(as_text=True)
            assert "EVIL=1" not in cc.ENV_FILE.read_text(encoding="utf-8")

            authed = client.post(
                "/api/setup/save_keys",
                json={"api_key": "AK" + "7" * 20, "secret_key": "SK" + "8" * 20},
                headers=_basic("operator", "secret"),
            )
            assert authed.status_code == 200, authed.get_data(as_text=True)
            assert "ALPACA_API_KEY=AK" + "7" * 20 in cc.ENV_FILE.read_text(encoding="utf-8")

            os.environ.pop("FORTRESS_DASHBOARD_USER", None)
            os.environ.pop("FORTRESS_DASHBOARD_PASS", None)
            unauth_halt = client.post("/api/operator/halt", json={"active": True, "reason": "smoke"})
            assert unauth_halt.status_code == 403, unauth_halt.get_data(as_text=True)

            os.environ["FORTRESS_OPERATOR_TOKEN"] = "halt-token"
            missing_token = client.post("/api/operator/halt", json={"active": True, "reason": "smoke"})
            assert missing_token.status_code == 403, missing_token.get_data(as_text=True)
            token_ok = client.post(
                "/api/operator/halt",
                json={"active": True, "reason": "smoke"},
                headers={"X-Operator-Token": "halt-token"},
            )
            assert token_ok.status_code == 200, token_ok.get_data(as_text=True)

        print("[smoke] smoke_dashboard_mutation_auth: PASS")
        return 0
    finally:
        os.chdir(old_cwd)
        _restore_env(env_snapshot)


if __name__ == "__main__":
    raise SystemExit(main())
