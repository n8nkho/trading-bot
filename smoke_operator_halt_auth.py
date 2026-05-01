#!/usr/bin/env python3
"""Smoke: operator halt POST requires explicit operator credentials."""
from __future__ import annotations

import base64
import os
import sys
import types
from contextlib import contextmanager


@contextmanager
def _patched_env(updates: dict[str, str | None]):
    old = {k: os.environ.get(k) for k in updates}
    try:
        for k, v in updates.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _basic(user: str, password: str) -> str:
    raw = f"{user}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def main() -> int:
    with _patched_env({
        "FORTRESS_OPERATOR_TOKEN": None,
        "FORTRESS_DASHBOARD_USER": None,
        "FORTRESS_DASHBOARD_PASS": None,
        "FORTRESS_ALERT_WEBHOOK_URL": None,
    }):
        # Keep this smoke focused on the halt route; the dashboard imports
        # analytics helpers that may need heavier optional packages.
        backtest_stub = types.ModuleType("utils.simple_daily_backtest")
        backtest_stub.read_backtest_snapshot = lambda *args, **kwargs: {}
        backtest_stub.run_daily_momentum_backtest = lambda *args, **kwargs: {}
        sys.modules.setdefault("utils.simple_daily_backtest", backtest_stub)

        import dashboard.command_center as cc

        writes: list[tuple[bool, str, str]] = []
        cc.set_trading_halt = lambda active, reason="", actor="dashboard": writes.append((active, reason, actor)) or {
            "active": active,
            "reason": reason,
            "actor": actor,
        }
        cc.send_operator_alert = lambda *args, **kwargs: False
        cc.append_trust_event = lambda *args, **kwargs: None

        client = cc.app.test_client()

        r = client.post("/api/operator/halt", json={"active": True})
        assert r.status_code == 403, r.get_data(as_text=True)
        assert not writes, writes

        with _patched_env({"FORTRESS_OPERATOR_TOKEN": "tok"}):
            r = client.post("/api/operator/halt", json={"active": True}, headers={"X-Operator-Token": "tok"})
            assert r.status_code == 200, r.get_data(as_text=True)
            assert writes[-1][0] is True

        with _patched_env({
            "FORTRESS_OPERATOR_TOKEN": None,
            "FORTRESS_DASHBOARD_USER": "ops",
            "FORTRESS_DASHBOARD_PASS": "secret",
        }):
            r = client.post("/api/operator/halt", json={"active": False}, headers={"Authorization": _basic("ops", "secret")})
            assert r.status_code == 200, r.get_data(as_text=True)
            assert writes[-1][0] is False

    print("[OK] smoke_operator_halt_auth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
