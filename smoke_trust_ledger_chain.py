#!/usr/bin/env python3
"""Smoke: trust ledger lines include chain_prev_sha256 linking to previous line hash."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import utils.trust_ledger as tl


def main() -> int:
    orig = tl.LEDGER_PATH
    path: Path | None = None
    try:
        fd, name = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        path = Path(name)
        tl.LEDGER_PATH = path
        tl.append_trust_event("smoke_chain_a", {"n": 1})
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        h1 = hashlib.sha256(lines[0].encode("utf-8")).hexdigest()
        assert (json.loads(lines[0]).get("chain_prev_sha256") or "") == ""

        tl.append_trust_event("smoke_chain_b", {"n": 2})
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        row2 = json.loads(lines[1])
        assert row2.get("chain_prev_sha256") == h1
    finally:
        tl.LEDGER_PATH = orig
        if path:
            path.unlink(missing_ok=True)

    print("[OK] smoke_trust_ledger_chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
