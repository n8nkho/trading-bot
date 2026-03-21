#!/usr/bin/env python3
"""Smoke: operational run registry append + summarize (Phase A)."""
from __future__ import annotations

import tempfile
from pathlib import Path


def main() -> int:
    import utils.run_registry as rr_mod

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "operational_runs.jsonl"
        prev = rr_mod.REGISTRY_PATH
        rr_mod.REGISTRY_PATH = p
        try:
            rr_mod.log_screening_started("smoke_run_x", "balanced", 10000.0)
            rr_mod.log_screening_completed(
                "smoke_run_x",
                {
                    "candidates_found": 2,
                    "approved_count": 0,
                    "executed_count": 0,
                    "rejected_count": 2,
                    "strict_mode": False,
                },
            )
            assert p.exists(), "operational_runs.jsonl missing"
            raw = p.read_text().strip().splitlines()
            assert len(raw) >= 2, "expected 2 jsonl rows"
            summ = rr_mod.summarize_screening_runs()
            assert summ, "summarize_screening_runs empty"
            top = summ[0]
            assert top.get("run_id") == "smoke_run_x"
            assert top.get("terminal") == "completed"
        finally:
            rr_mod.REGISTRY_PATH = prev
        print("[OK] smoke_operator_run_registry")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
