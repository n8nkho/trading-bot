"""
JSON queue of approved trades deferred for human review (human-in-the-loop mode).

File: ``data/pending_execution_queue.json`` with shape::

    {"batches": [{"updated_at", "source", "run_id", "candidates", "trades"}, ...]}
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def pending_queue_path(data_dir: Path | None = None) -> Path:
    root = data_dir if data_dir is not None else Path("data")
    return root / "pending_execution_queue.json"


def _write_queue(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def append_pending_batch(
    *,
    source: str,
    run_id: str,
    candidates: list,
    trades: list,
    data_dir: Path | None = None,
) -> Path:
    """Append one batch. Creates ``data_dir`` if needed."""
    path = pending_queue_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"batches": []}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"Could not read existing pending execution queue: {e}") from e
    batches = data.get("batches")
    if not isinstance(batches, list):
        batches = []
    batches.append(
        {
            "updated_at": datetime.now().isoformat(),
            "source": source,
            "run_id": run_id,
            "candidates": candidates,
            "trades": trades,
        }
    )
    data["batches"] = batches
    _write_queue(path, data)
    return path


def load_batches(data_dir: Path | None = None) -> list[dict[str, Any]]:
    path = pending_queue_path(data_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    batches = data.get("batches")
    return batches if isinstance(batches, list) else []


def clear_batches(data_dir: Path | None = None) -> None:
    write_batches([], data_dir=data_dir)


def write_batches(batches: list[dict[str, Any]], data_dir: Path | None = None) -> None:
    path = pending_queue_path(data_dir)
    _write_queue(path, {"batches": batches})


def pending_summary(data_dir: Path | None = None) -> dict[str, Any]:
    batches = load_batches(data_dir)
    n_trades = 0
    for b in batches:
        if isinstance(b, dict):
            t = b.get("trades")
            if isinstance(t, list):
                n_trades += len(t)
    return {
        "batch_count": len(batches),
        "trade_count": n_trades,
        "path": str(pending_queue_path(data_dir)),
    }
