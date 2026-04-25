"""Tests for critique loop JSON parsing and dry-run evaluation."""

from __future__ import annotations

import json

from agents.critique_loop import _parse_json_response, evaluate_with_critique


def test_parse_json_plain_object():
    raw = '{"decision": "BUY", "confidence": 0.8, "reasoning": "ok"}'
    out = _parse_json_response(raw)
    assert out == {"decision": "BUY", "confidence": 0.8, "reasoning": "ok"}


def test_parse_json_fenced():
    raw = """Here is the result:
```json
{"verdict": "CONFIRM", "critique": "fine"}
```
"""
    out = _parse_json_response(raw)
    assert out == {"verdict": "CONFIRM", "critique": "fine"}


def test_evaluate_dry_run_modify():
    signal = {"symbol": "SPY", "direction": "BUY", "confidence": 0.65}
    trade = {"symbol": "SPY", "side": "buy", "shares": 10}
    r = evaluate_with_critique(signal, trade, dry_run=True)
    assert r["proceed"] is True
    assert r["size_multiplier"] == 0.5
    assert r["verdict"] == "MODIFY"


def test_trade_history_append(tmp_path, monkeypatch):
    import utils.trade_history as th

    monkeypatch.setattr(th, "_PATH", tmp_path / "trade_history.json")
    (tmp_path / "trade_history.json").write_text('{"trades": []}', encoding="utf-8")
    tid = th.append_closed_trade({"ticker": "TEST", "pnl_dollars": 1.0})
    assert tid
    doc = json.loads((tmp_path / "trade_history.json").read_text(encoding="utf-8"))
    assert len(doc["trades"]) == 1
    assert doc["trades"][0]["ticker"] == "TEST"


def test_atomic_json_roundtrip(tmp_path):
    from utils.atomic_json import read_json, write_json_atomic

    p = tmp_path / "nested" / "x.json"
    write_json_atomic(p, {"a": 1})
    assert read_json(p, {}) == {"a": 1}
