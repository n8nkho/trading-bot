#!/usr/bin/env python3
"""
Smoke: mutating Command Center operator endpoints require auth.
"""

from __future__ import annotations

import base64
import os
import sys
from contextlib import contextmanager
from unittest.mock import patch


AUTH_ENV_KEYS = (
    "FORTRESS_OPERATOR_TOKEN",
    "FORTRESS_DASHBOARD_USER",
    "FORTRESS_DASHBOARD_PASS",
)


@contextmanager
def _auth_env(**values):
    old = {k: os.environ.get(k) for k in AUTH_ENV_KEYS}
    try:
        for key in AUTH_ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in values.items():
            if value is not None:
                os.environ[key] = value
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _basic_header(user: str, password: str) -> dict[str, str]:
    raw = f"{user}:{password}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def main() -> int:
    from dashboard import command_center as cc
    import utils.policy_guardrails as policy_guardrails

    app = cc.app
    app.config["TESTING"] = True

    halt_state = {"file": {"active": False}, "effective_halted": False}
    with app.test_client() as client:
        with _auth_env():
            with patch.object(cc, "set_trading_halt") as set_halt:
                r = client.post("/api/operator/halt", json={"active": True})
                assert r.status_code == 403, r.get_data(as_text=True)
                set_halt.assert_not_called()

            with patch.object(policy_guardrails, "clear_forced_rollback") as clear_rollback:
                r = client.post("/api/policy/clear_rollback", json={})
                assert r.status_code == 403, r.get_data(as_text=True)
                clear_rollback.assert_not_called()

        with _auth_env(FORTRESS_OPERATOR_TOKEN="operator-secret"):
            with (
                patch.object(cc, "get_halt_state", return_value=halt_state),
                patch.object(cc, "set_trading_halt", return_value={"active": True}) as set_halt,
                patch.object(cc, "send_operator_alert"),
                patch.object(cc, "append_trust_event"),
            ):
                r = client.post(
                    "/api/operator/halt",
                    json={"active": True, "reason": "smoke"},
                    headers={"X-Operator-Token": "operator-secret"},
                )
                assert r.status_code == 200, r.get_data(as_text=True)
                set_halt.assert_called_once()

            with patch.object(policy_guardrails, "clear_forced_rollback", return_value={"cleared_at": "smoke"}):
                r = client.post(
                    "/api/policy/clear_rollback",
                    json={},
                    headers={"X-Operator-Token": "operator-secret"},
                )
                assert r.status_code == 200, r.get_data(as_text=True)

        with _auth_env(FORTRESS_DASHBOARD_USER="operator", FORTRESS_DASHBOARD_PASS="pass123"):
            headers = _basic_header("operator", "pass123")
            with (
                patch.object(cc, "get_halt_state", return_value=halt_state),
                patch.object(cc, "set_trading_halt", return_value={"active": False}) as set_halt,
                patch.object(cc, "send_operator_alert"),
                patch.object(cc, "append_trust_event"),
            ):
                r = client.post("/api/operator/halt", json={"active": False}, headers=headers)
                assert r.status_code == 200, r.get_data(as_text=True)
                set_halt.assert_called_once()

    print("[OK] dashboard operator mutating endpoints require auth")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        raise SystemExit(1)
