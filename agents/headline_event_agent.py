"""
Headline event agent (v1 sketch): ingest labeled events, persist ledger, emit shadow-only hints.

No live orders. See docs/HEADLINE_EVENT_AGENT_SKETCH.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_CANDIDATES = ("headline_event_agent.yaml", "headline_event_agent.example.yaml")
EVENTS_FILE = "headline_events.jsonl"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("Could not load YAML %s: %s", path, e)
        return {}


def load_config() -> dict[str, Any]:
    root = _repo_root()
    for name in CONFIG_CANDIDATES:
        p = root / "config" / name
        if p.is_file():
            cfg = _load_yaml(p)
            if cfg:
                return cfg
    return {
        "mode": "shadow_only",
        "enabled": True,
        "universe": {"require_prior_screen_approval": True},
        "shadow": {"output_dir": "data", "file_prefix": "headline_event_shadow_"},
        "horizons": ["intraday", "5d"],
    }


def _quality_tickers() -> set[str]:
    root = _repo_root()
    p = root / "config" / "watchlist.json"
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {
            str(x.get("ticker", "")).strip().upper()
            for x in (data.get("quality_stocks") or [])
            if x.get("ticker")
        }
    except (OSError, json.JSONDecodeError):
        return set()


def _text_hash(title: str, summary: str) -> str:
    raw = f"{title.strip()}|{summary.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _recent_hashes(path: Path, max_lines: int = 2000) -> set[str]:
    if not path.is_file():
        return set()
    out: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-max_lines:]:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                h = rec.get("text_hash")
                if h:
                    out.add(str(h))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return out


def _shadow_action_for_topics(topics: list[str]) -> str:
    t = {str(x).lower() for x in topics}
    if "tariffs" in t or "war_risk" in t:
        return "watch"
    if "fed_policy" in t:
        return "watch"
    return "watch"


def _load_fixture_events(fixture_path: Path) -> list[dict[str, Any]]:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return list(data.get("events") or [])


def run_headline_event_cycle(fixture_path: Path | None = None) -> dict[str, Any]:
    """
    Run one cycle: optional fixture ingest -> append events -> write shadow JSONL.
    Returns a small summary dict for orchestrator / smoke.
    """
    if os.getenv("HEADLINE_EVENT_AGENT_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        return {"ok": True, "skipped": True, "reason": "HEADLINE_EVENT_AGENT_ENABLED off"}

    cfg = load_config()
    if not cfg.get("enabled", True):
        return {"ok": True, "skipped": True, "reason": "config enabled=false"}

    root = _repo_root()
    data_dir = root / (cfg.get("shadow", {}) or {}).get("output_dir", "data")
    data_dir.mkdir(parents=True, exist_ok=True)

    events_path = data_dir / EVENTS_FILE
    known_hashes = _recent_hashes(events_path)

    if fixture_path is None:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_fixture_configure_RSS_or_run_with_--fixture",
            "events_appended": 0,
            "shadow_written": 0,
        }

    if not fixture_path.is_file():
        return {"ok": False, "error": f"missing_fixture:{fixture_path}"}

    raw_events = _load_fixture_events(fixture_path)
    require_wl = bool((cfg.get("universe") or {}).get("require_prior_screen_approval", True))
    quality = _quality_tickers()
    horizons = list(cfg.get("horizons") or ["intraday", "5d"])

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = (cfg.get("shadow", {}) or {}).get("file_prefix", "headline_event_shadow_")
    shadow_path = data_dir / f"{prefix}{day}.jsonl"

    appended = 0
    shadow_rows = 0

    for ev in raw_events:
        title = str(ev.get("title") or "").strip()
        summary = str(ev.get("summary") or "").strip()
        topics = [str(x) for x in (ev.get("topics") or []) if x]
        entities = [str(x).strip().upper() for x in (ev.get("entities") or []) if x]

        th = _text_hash(title, summary)
        if th in known_hashes:
            continue

        event_id = str(uuid.uuid4())
        ingested = datetime.now(timezone.utc).isoformat()
        record = {
            "event_id": event_id,
            "ingested_at_utc": ingested,
            "published_at_utc": None,
            "source": "fixture",
            "source_item_id": fixture_path.name,
            "text_hash": th,
            "title": title[:500],
            "summary": summary[:2000],
            "raw_ref": str(fixture_path),
            "topics": topics,
            "entities": entities,
            "confidence": 1.0,
            "version": "1",
        }
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        known_hashes.add(th)
        appended += 1

        action = _shadow_action_for_topics(topics)
        tickers = set(entities)
        if require_wl:
            tickers = tickers.intersection(quality)

        for sym in sorted(tickers):
            for hz in horizons:
                row = {
                    "ts_utc": ingested,
                    "event_id": event_id,
                    "ticker": sym,
                    "horizon": hz,
                    "suggested_action": action,
                    "rationale_short": f"shadow_only topics={topics}",
                    "mode": str(cfg.get("mode") or "shadow_only"),
                }
                with open(shadow_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, default=str) + "\n")
                shadow_rows += 1

    return {
        "ok": True,
        "events_appended": appended,
        "shadow_written": shadow_rows,
        "events_path": str(events_path),
        "shadow_path": str(shadow_path),
        "fixture": str(fixture_path),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fp = _repo_root() / "tests" / "fixtures" / "headline_event_sample.json"
    print(json.dumps(run_headline_event_cycle(fixture_path=fp), indent=2))
