"""Atomic JSON read/write for state files under data/."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: str | Path, default: Any = None) -> Any:
    """Read JSON file; return default if missing or invalid."""
    p = Path(path)
    try:
        if not p.exists():
            return default
        raw = p.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception:
        return default


def write_json_atomic(path: str | Path, obj: Any, *, indent: int = 2) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    """Alias for atomic JSON write (temp file + os.replace)."""
    write_json_atomic(path, data, indent=indent)


def append_json_list(path: str | Path, record: dict) -> None:
    """Atomically append a record to JSON shaped as {"items": [...]}."""
    path = Path(path)
    data = read_json(path, default={"items": []})
    if not isinstance(data, dict) or "items" not in data:
        data = {"items": []}
    if not isinstance(data["items"], list):
        data["items"] = []
    data["items"].append(record)
    write_json_atomic(path, data)
