#!/usr/bin/env python3
"""
Smoke: headline event dashboard status follows the agent's configured output path.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "headline_event_agent.yaml"


def _write_unique_fixture(tmpdir: Path) -> Path:
    base = ROOT / "tests" / "fixtures" / "headline_event_sample.json"
    data = json.loads(base.read_text(encoding="utf-8"))
    events = data.get("events") or []
    if events:
        events[0]["title"] = f"{events[0].get('title', '')} [status smoke {time.time()}]"
    fixture = tmpdir / "headline_event_status_fixture.json"
    fixture.write_text(json.dumps(data), encoding="utf-8")
    return fixture


def _install_dashboard_import_stubs() -> None:
    """Keep this smoke focused when the cloud image has not installed web deps."""
    if "flask" not in sys.modules:
        flask = types.ModuleType("flask")

        class _DummyFlask:
            def __init__(self, *args, **kwargs):
                self.config = {}

            def route(self, *args, **kwargs):
                return lambda func: func

            def before_request(self, func):
                return func

        flask.Flask = _DummyFlask
        flask.render_template = lambda *args, **kwargs: ""
        flask.jsonify = lambda *args, **kwargs: args[0] if len(args) == 1 else list(args)
        flask.make_response = lambda *args, **kwargs: args[0] if args else None
        flask.redirect = lambda *args, **kwargs: None
        flask.url_for = lambda *args, **kwargs: ""
        flask.Response = lambda *args, **kwargs: None
        flask.request = types.SimpleNamespace(
            path="",
            authorization=None,
            headers={},
            get_json=lambda *args, **kwargs: {},
        )
        sys.modules["flask"] = flask

    if "flask_cors" not in sys.modules:
        flask_cors = types.ModuleType("flask_cors")
        flask_cors.CORS = lambda *args, **kwargs: None
        sys.modules["flask_cors"] = flask_cors


def main() -> int:
    original = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None
    tmp_root = Path(tempfile.mkdtemp(prefix="headline-event-status-"))
    out_dir = tmp_root / "custom-shadow-output"
    prefix = "status_regression_shadow_"

    try:
        CONFIG_PATH.write_text(
            "\n".join(
                [
                    "mode: shadow_only",
                    "enabled: true",
                    "universe:",
                    "  require_prior_screen_approval: false",
                    "shadow:",
                    f"  output_dir: {out_dir}",
                    f"  file_prefix: {prefix}",
                    "horizons:",
                    "  - intraday",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        from agents.headline_event_agent import run_headline_event_cycle

        fixture = _write_unique_fixture(tmp_root)
        run_result = run_headline_event_cycle(fixture_path=fixture)
        if not run_result.get("ok"):
            print(f"[FAIL] headline_event_agent run failed: {run_result}")
            return 1
        if int(run_result.get("events_appended") or 0) < 1:
            print(f"[FAIL] expected at least one appended event: {run_result}")
            return 1
        if int(run_result.get("shadow_written") or 0) < 1:
            print(f"[FAIL] expected at least one shadow row: {run_result}")
            return 1

        _install_dashboard_import_stubs()
        from dashboard.command_center import get_headline_event_status

        status = get_headline_event_status()
        expected_events_path = str(out_dir / "headline_events.jsonl")
        if status.get("events_path") != expected_events_path:
            print(f"[FAIL] status events_path={status.get('events_path')} expected={expected_events_path}")
            return 1
        if int(status.get("events_line_count") or 0) < 1:
            print(f"[FAIL] status missed custom event ledger: {status}")
            return 1
        if not str(status.get("shadow_latest_name") or "").startswith(prefix):
            print(f"[FAIL] status missed custom shadow prefix: {status}")
            return 1
        if not status.get("shadow_preview"):
            print(f"[FAIL] status missed custom shadow rows: {status}")
            return 1
    finally:
        if original is None:
            try:
                CONFIG_PATH.unlink()
            except FileNotFoundError:
                pass
        else:
            CONFIG_PATH.write_text(original, encoding="utf-8")
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("[OK] headline_event_status follows configured output_dir and file_prefix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
