#!/usr/bin/env python3
"""Smoke: dashboard state-changing APIs require auth after first-run setup."""
from __future__ import annotations

import base64
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path


def _stub_module(name: str, **attrs) -> None:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod


def _install_import_stubs() -> None:
    _stub_module("utils.market_assets", require_market_assets=lambda: {})
    _stub_module(
        "utils.trust_ledger",
        append_trust_event=lambda *a, **k: None,
        enrich_trust_ledger_items=lambda items, *a, **k: items,
        read_recent_trust_events=lambda *a, **k: [],
    )
    _stub_module("utils.alerts", send_operator_alert=lambda *a, **k: None)
    _stub_module(
        "utils.simple_daily_backtest",
        read_backtest_snapshot=lambda *a, **k: {},
        run_daily_momentum_backtest=lambda *a, **k: {},
    )
    _stub_module("utils.run_registry", summarize_screening_runs=lambda *a, **k: {})
    _stub_module("agents.drift_detector", analyze_drift=lambda *a, **k: {})


def _basic(user: str, password: str) -> dict[str, str]:
    raw = f"{user}:{password}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def main() -> int:
    _install_import_stubs()
    os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
    os.environ["FORTRESS_DASHBOARD_PASS"] = "secret"
    os.environ.pop("FORTRESS_OPERATOR_TOKEN", None)

    import dashboard.command_center as cc

    td = Path(tempfile.mkdtemp())
    try:
        data_dir = td / "data"
        data_dir.mkdir()
        cc.DATA_DIR = data_dir
        cc.ENV_FILE = td / ".env"
        cc.SETUP_COMPLETE_FILE = data_dir / "setup_complete"

        state = {"file": {"active": False}}
        cc.get_halt_state = lambda: {"env_halt": False, "file": state["file"], "effective_halted": bool(state["file"].get("active"))}

        def _fake_set_halt(active, reason="", actor="dashboard"):
            state["file"] = {"active": bool(active), "reason": reason, "actor": actor}
            return state["file"]

        cc.set_trading_halt = _fake_set_halt
        cc.send_operator_alert = lambda *a, **k: None
        cc.append_trust_event = lambda *a, **k: None

        client = cc.app.test_client()

        # First-run setup remains possible without credentials before any keys exist.
        rv = client.post(
            "/api/setup/save_keys",
            json={"api_key": "PK" + "A" * 16, "secret_key": "SK" + "B" * 24},
        )
        assert rv.status_code == 200, rv.get_data(as_text=True)
        assert "ALPACA_API_KEY=" in cc.ENV_FILE.read_text(encoding="utf-8")

        # Once setup is complete, unauthenticated credential overwrite is blocked.
        cc.SETUP_COMPLETE_FILE.write_text("ok", encoding="utf-8")
        rv = client.post(
            "/api/setup/save_keys",
            json={"api_key": "PK" + "C" * 16, "secret_key": "SK" + "D" * 24},
        )
        assert rv.status_code == 403, rv.get_data(as_text=True)

        # Authenticated credential writes reject newline injection into .env.
        rv = client.post(
            "/api/setup/save_keys",
            headers=_basic("operator", "secret"),
            json={"api_key": "PK" + "E" * 16, "secret_key": "SK" + "F" * 12 + "\nALPACA_BASE_URL=https://api.alpaca.markets"},
        )
        assert rv.status_code == 400, rv.get_data(as_text=True)
        assert "api.alpaca.markets" not in cc.ENV_FILE.read_text(encoding="utf-8")

        rv = client.post(
            "/api/setup/save_keys",
            headers=_basic("operator", "secret"),
            json={"api_key": "PK" + "G" * 16, "secret_key": "SK" + "H" * 24},
        )
        assert rv.status_code == 200, rv.get_data(as_text=True)

        # Halt/resume and policy rollback are state-changing and require auth/token.
        os.environ.pop("FORTRESS_DASHBOARD_USER", None)
        os.environ.pop("FORTRESS_DASHBOARD_PASS", None)
        rv = client.post("/api/operator/halt", json={"active": False})
        assert rv.status_code == 403, rv.get_data(as_text=True)
        rv = client.post("/api/policy/clear_rollback", json={})
        assert rv.status_code == 403, rv.get_data(as_text=True)

        os.environ["FORTRESS_DASHBOARD_USER"] = "operator"
        os.environ["FORTRESS_DASHBOARD_PASS"] = "secret"
        rv = client.post("/api/operator/halt", headers=_basic("operator", "secret"), json={"active": True, "reason": "smoke"})
        assert rv.status_code == 200, rv.get_data(as_text=True)
        assert state["file"]["active"] is True
    finally:
        shutil.rmtree(td, ignore_errors=True)

    print("[OK] smoke_dashboard_mutation_auth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
