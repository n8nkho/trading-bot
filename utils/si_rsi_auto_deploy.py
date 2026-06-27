"""Auto-commit/push Classic RSI screener / adaptive_rsi fixes."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent

_RSI_PATHS = frozenset(
    {
        "utils/adaptive_rsi.py",
        "utils/adaptive_rsi_reconciliation.py",
        "utils/classic_si_screener.py",
        "data/screener_si_overrides.json",
        "tests/test_adaptive_rsi.py",
        "tests/test_adaptive_rsi_reconciliation.py",
        "tests/test_classic_si_screener.py",
    }
)


def rsi_auto_commit_enabled() -> bool:
    return str(os.environ.get("FORTRESS_SI_RSI_AUTO_COMMIT", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def rsi_auto_push_enabled() -> bool:
    return str(os.environ.get("FORTRESS_SI_RSI_AUTO_PUSH", "1")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _normalize_rel(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_rsi_deploy_path(path: str) -> bool:
    norm = _normalize_rel(path)
    if norm in _RSI_PATHS:
        return True
    return norm.startswith("tests/") and "rsi" in norm.lower()


def deploy_screener_relax(*, reason: str = "classic_si_screener_relax") -> dict[str, Any]:
    """Commit screener SI overrides after a relax step is applied."""
    if not rsi_auto_commit_enabled():
        return {"ok": True, "skipped": "rsi_commit_disabled"}
    paths = ["data/screener_si_overrides.json", "utils/classic_si_screener.py"]
    try:
        subprocess.run(["git", "add", "--"] + paths, cwd=_ROOT, check=False, timeout=30)
        r = subprocess.run(
            ["git", "commit", "-m", f"chore(rsi): screener relax ({reason})"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0 and "nothing to commit" in (r.stdout + r.stderr):
            return {"ok": True, "skipped": "nothing_to_commit"}
        if r.returncode != 0:
            return {"ok": False, "commit": (r.stdout or r.stderr or "")[-400:]}
        if rsi_auto_push_enabled():
            p = subprocess.run(
                ["git", "push", "origin", "master"],
                cwd=_ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return {"ok": p.returncode == 0, "push": (p.stdout or p.stderr or "")[-400:]}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
