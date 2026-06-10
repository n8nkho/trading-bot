"""
JSON queue of approved trades deferred for human review (human-in-the-loop mode).

File: ``data/pending_execution_queue.json`` with shape::

    {"batches": [{"updated_at", "source", "run_id", "candidates", "trades"}, ...]}
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def pending_queue_path(data_dir: Path | None = None) -> Path:
    root = data_dir if data_dir is not None else Path("data")
    return root / "pending_execution_queue.json"


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
        except Exception:
            data = {"batches": []}
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
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
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
    path = pending_queue_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"batches": []}, indent=2), encoding="utf-8")


def replace_batches(batches: list[dict[str, Any]], data_dir: Path | None = None) -> None:
    """Replace the queue contents with the supplied batches."""
    path = pending_queue_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"batches": batches}, indent=2, default=str), encoding="utf-8")


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
