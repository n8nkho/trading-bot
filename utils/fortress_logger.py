"""Structured + human logs with light retention for Fortress agent files."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parent.parent
_LOGS = Path(os.getenv("FORTRESS_LOG_DIR", str(_ROOT / "logs")))
_RETENTION_DAYS = 30
_PRUNE_NAMES = (
    "critique.log",
    "reflection.log",
    "briefing.log",
    "alerts.log",
    "reflection_alert.log",
    "screener.log",
    "risk.log",
    "orchestrator.log",
    "monitor.log",
    "exit_monitor.log",
    "sentiment_velocity.log",
    "earnings_intel.log",
    "options_flow.log",
    "cross_asset.log",
    "regime.log",
    "prompt_evolution.log",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _et_now_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S %Z")


_last_prune = 0.0


def _maybe_prune() -> None:
    global _last_prune
    now = time.time()
    if now - _last_prune < 3600:
        return
    _last_prune = now
    cutoff = now - _RETENTION_DAYS * 86400
    try:
        if not _LOGS.is_dir():
            return
        for p in _LOGS.iterdir():
            if not p.is_file():
                continue
            if (
                p.name not in _PRUNE_NAMES
                and not p.name.startswith("briefing_")
                and not p.name.startswith("backtest_")
            ):
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except OSError:
                pass
    except Exception:
        pass


def _append_log_line(filename: str, line: str) -> None:
    _maybe_prune()
    _LOGS.mkdir(parents=True, exist_ok=True)
    path = _LOGS / filename
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")
        f.flush()


def get_logger(name: str, log_file: str | None = None) -> logging.Logger:
    """Named logger with optional file handler (Fortress-compatible)."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    if log_file:
        _LOGS.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(_LOGS / log_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def append_critique_log(line: str) -> None:
    _append_log_line("critique.log", line)


def append_alerts_log(line: str) -> None:
    _append_log_line("alerts.log", line)


def append_log(filename: str, line: str) -> None:
    """Generic helper for single-line append into logs/<filename>."""
    _append_log_line(filename, line)


class FortressLogger:
    def __init__(self, name: str = "fortress"):
        self.name = name
        _LOGS.mkdir(parents=True, exist_ok=True)

    def _append(self, filename: str, line: str) -> None:
        _append_log_line(filename, line)

    def log_critique(self, human_line: str) -> None:
        self._append("critique.log", human_line)

    def log_reflection(self, payload: dict) -> None:
        self._append("reflection.log", json.dumps({"ts_utc": _utc_now_iso(), **payload}, default=str))

    def log_briefing(self, text: str, *, dated_filename: str | None = None) -> None:
        if dated_filename:
            self._append(dated_filename, text)
        self._append("briefing.log", text)

    def log_alert(self, message: str) -> None:
        line = f"[{_et_now_str()}] {message}"
        self._append("alerts.log", line)

    def log_trade(self, payload: dict) -> None:
        self._append("fortress_trades.log", json.dumps({"ts_utc": _utc_now_iso(), **payload}, default=str))
