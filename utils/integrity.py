"""
Core integrity check: detect if delivered code was modified.

Optional. When license has "integrity_check": true, this module compares
hashes of core files under agents/, config/, orchestrator.py, etc. against
data/integrity_manifest.json. Manifest is generated at build time (scripts/build_manifest.py)
and shipped with customer deployments; it is not in the master repo.

If any hash mismatches, we log a warning and can disable auto-trading or
downgrade to Starter until restored. Prevents casual editing of core code.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = PROJECT_ROOT / "data" / "integrity_manifest.json"

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_integrity(manifest_path: Path | None = None) -> tuple[bool, list[str]]:
    """
    Compare current core files to manifest. Returns (ok, list of mismatch descriptions).
    If manifest missing or invalid, returns (True, []) so master/unlicensed runs are unaffected.
    """
    path = manifest_path or MANIFEST_FILE
    if not path.exists():
        return True, []
    try:
        with open(path) as f:
            manifest = json.load(f)
    except Exception:
        return True, []

    if not isinstance(manifest, dict) or "files" not in manifest:
        return True, []

    errors = []
    for rel_path, expected_hash in manifest.get("files", {}).items():
        full = PROJECT_ROOT / rel_path
        if not full.exists():
            errors.append(f"missing:{rel_path}")
            continue
        try:
            actual = _file_hash(full)
            if actual != expected_hash:
                errors.append(f"modified:{rel_path}")
        except Exception as e:
            errors.append(f"error:{rel_path} ({e})")

    return (len(errors) == 0, errors)
