"""
Smoke test: ensure risk_guardian circuit breaker state persists.
"""

import importlib
import json
from pathlib import Path


def main():
    import agents.risk_guardian as rg

    state_file = Path("data") / "risk_guardian_state.json"
    state_file.parent.mkdir(exist_ok=True, parents=True)

    # Write a known state.
    state_file.write_text(
        json.dumps(
            {
                "consecutive_losses": 3,
                "circuit_breaker_active": True,
                "position_size_reduction": 0.5,
                "updated_at": "2026-01-01T00:00:00",
            }
        ),
        encoding="utf-8",
    )

    # Reload module to trigger _load_risk_state.
    importlib.reload(rg)
    assert rg.consecutive_losses == 3
    assert rg.circuit_breaker_active is True
    assert abs(rg.position_size_reduction - 0.5) < 1e-9

    # Simulate the dashboard staying alive while a separate orchestrator/cron
    # process updates the persisted state. get_risk_status must not report the
    # stale import-time globals.
    state_file.write_text(
        json.dumps(
            {
                "consecutive_losses": 2,
                "circuit_breaker_active": False,
                "position_size_reduction": 0.5,
                "updated_at": "2026-01-01T00:05:00",
            }
        ),
        encoding="utf-8",
    )
    status = rg.get_risk_status()
    assert int(status.get("consecutive_losses", 0)) == 2, status
    assert status.get("circuit_breaker_active") is False, status

    # Restore the original stressed state before testing in-process updates.
    state_file.write_text(
        json.dumps(
            {
                "consecutive_losses": 3,
                "circuit_breaker_active": True,
                "position_size_reduction": 0.5,
                "updated_at": "2026-01-01T00:10:00",
            }
        ),
        encoding="utf-8",
    )
    assert int(rg.get_risk_status().get("consecutive_losses", 0)) == 3

    # Apply a loss update and confirm file changed.
    rg.update_consecutive_losses({"pnl": -10.0})
    after = json.loads(state_file.read_text(encoding="utf-8"))
    assert int(after.get("consecutive_losses", 0)) == 4

    print("[smoke] smoke_risk_state_persistence: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

