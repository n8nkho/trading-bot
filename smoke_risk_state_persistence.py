"""
Smoke test: ensure risk_guardian circuit breaker state persists.
"""

import importlib
import json
import os
from pathlib import Path
import tempfile


def main():
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        try:
            state_file = Path("data") / "risk_guardian_state.json"
            state_file.parent.mkdir(exist_ok=True, parents=True)

            # Write a known active state with an inconsistent count. The active
            # flag must still block trading until an explicit reset.
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

            import agents.risk_guardian as rg
            importlib.reload(rg)
            assert rg.consecutive_losses == 3
            assert rg.circuit_breaker_active is True
            assert abs(rg.position_size_reduction - 0.5) < 1e-9

            risk_check = rg.check_risk_limits(
                {"equity": 10000, "positions": [], "today_pnl": 0},
                {"ticker": "HALT", "size": 1, "value": 100, "sector": "Test"},
            )
            assert risk_check["approved"] is False
            assert "circuit breaker active" in risk_check["reason"]

            # Apply a loss update and confirm file changed atomically to valid JSON.
            rg.update_consecutive_losses({"pnl": -10.0})
            after = json.loads(state_file.read_text(encoding="utf-8"))
            assert int(after.get("consecutive_losses", 0)) == 4
            assert after.get("circuit_breaker_active") is True

            # A corrupt persisted state should fail closed rather than reset the halt.
            state_file.write_text('{"consecutive_losses": 5,', encoding="utf-8")
            importlib.reload(rg)
            assert rg.consecutive_losses >= rg.CIRCUIT_BREAKER_HALT_THRESHOLD
            assert rg.circuit_breaker_active is True
            assert rg.position_size_reduction <= 0.5

            corrupt_check = rg.check_risk_limits(
                {"equity": 10000, "positions": [], "today_pnl": 0},
                {"ticker": "CORRUPT", "size": 1, "value": 100, "sector": "Test"},
            )
            assert corrupt_check["approved"] is False
        finally:
            os.chdir(original_cwd)

    print("[smoke] smoke_risk_state_persistence: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

