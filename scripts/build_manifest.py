#!/usr/bin/env python3
"""
Build integrity manifest for customer deployments.

Run from project root. Hashes core files and writes data/integrity_manifest.json.
Ship this file with the customer build; the bot will refuse to run (or will
downgrade) if any listed file is modified.

  python scripts/build_manifest.py
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    # Paths relative to project root
    patterns = [
        "orchestrator.py",
        "run_strategies.py",
        "check_health.py",
        "config/license.py",
        "config/tiers.py",
        "config/customer_settings.py",
        "config/addon_loader.py",
        "agents/screener_agent.py",
        "agents/entry_agent.py",
        "agents/exit_monitor.py",
        "agents/risk_guardian.py",
    ]
    files = []
    for p in patterns:
        path = ROOT / p
        if path.exists():
            files.append(p)
    # Add all agents/*.py
    for f in sorted((ROOT / "agents").glob("*.py")):
        rel = str(f.relative_to(ROOT))
        if rel not in files:
            files.append(rel)

    manifest = {"files": {}}
    for rel in sorted(files):
        full = ROOT / rel
        manifest["files"][rel] = _file_hash(full)

    out = ROOT / "data" / "integrity_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote {len(manifest['files'])} entries to {out}")


if __name__ == "__main__":
    main()
