#!/usr/bin/env python3
"""
Smoke: headline_event_agent (fixture, shadow JSONL) + Alpaca paper limit submit + cancel.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _unique_fixture() -> Path:
    base = ROOT / "tests" / "fixtures" / "headline_event_sample.json"
    data = json.loads(base.read_text(encoding="utf-8"))
    evs = data.get("events") or []
    if evs:
        evs[0]["title"] = f"{evs[0].get('title', '')} [smoke {time.time()}]"
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
        dir=str(ROOT / "tests" / "fixtures"),
    )
    json.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


def main() -> int:
    from agents.headline_event_agent import run_headline_event_cycle

    fx = _unique_fixture()
    try:
        out = run_headline_event_cycle(fixture_path=fx)
    finally:
        try:
            fx.unlink(missing_ok=True)
        except OSError:
            pass

    if not out.get("ok"):
        print("[FAIL] headline_event_agent:", out, file=sys.stderr)
        return 1
    if int(out.get("events_appended") or 0) < 1:
        print("[FAIL] expected events_appended>=1 got", out, file=sys.stderr)
        return 1
    if int(out.get("shadow_written") or 0) < 1:
        print("[FAIL] expected shadow_written>=1 got", out, file=sys.stderr)
        return 1
    print(f"[OK] headline_event_agent events={out.get('events_appended')} shadow={out.get('shadow_written')}")

    import smoke_alpaca_paper_trade_cancel as alp

    code = alp.main()
    if code != 0:
        print("[FAIL] smoke_alpaca_paper_trade_cancel", file=sys.stderr)
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
