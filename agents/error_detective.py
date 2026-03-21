#!/usr/bin/env python3
"""
Error Detective agent.

Root-cause fix:
- Cron expected `agents/error_detective.py`, but the file did not exist.
- This script provides a safe, non-destructive daily error scan so the scheduled
  job can run and System Health validation no longer reports a missing-file error.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
MAX_FILES = 20
TAIL_LINES = 200


def _tail_lines(path: Path, n: int) -> list[str]:
    try:
        lines = path.read_text(errors="ignore").splitlines()
        return lines[-n:]
    except Exception:
        return []


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    log_files = sorted(LOGS_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_FILES]
    markers = re.compile(r"(traceback|error|exception|modulenotfounderror|importerror)", re.IGNORECASE)

    counts: Counter[str] = Counter()
    for log_path in log_files:
        for line in _tail_lines(log_path, TAIL_LINES):
            if markers.search(line):
                counts[log_path.name] += 1

    print(f"[error_detective] scan_time_utc={now} files_scanned={len(log_files)}")
    if not counts:
        print("[error_detective] status=OK no error markers in recent log tails")
        return 0

    print("[error_detective] status=WARN found error markers (top files):")
    for name, count in counts.most_common(8):
        print(f"  - {name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

