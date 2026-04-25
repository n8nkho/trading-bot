"""RecursiveScreener: passthrough when disabled; structure when enabled."""

from __future__ import annotations

from agents import screener_agent as sa


def test_recursive_disabled_passthrough(monkeypatch):
    monkeypatch.delenv("FORTRESS_RECURSIVE_SCREENER_ENABLED", raising=False)
    raw = [{"ticker": "AAA", "current_price": 50.0}]
    out = sa.RecursiveScreener().screen_candidates(raw)
    assert out == raw


def test_recursive_enabled_empty_in_empty_out(monkeypatch):
    monkeypatch.setenv("FORTRESS_RECURSIVE_SCREENER_ENABLED", "1")
    monkeypatch.setenv("FORTRESS_RECURSIVE_SCREENER_LLM_DRY_RUN", "1")
    out = sa.RecursiveScreener().screen_candidates([])
    assert out == []


def test_parse_json_llm_nested():
    blob = 'prefix {"stance": "contradict", "notes": "bad"} suffix'
    assert sa._parse_json_llm(blob)["stance"] == "contradict"


def test_daily_pnl_sum_tmp(tmp_path, monkeypatch):
    p = tmp_path / "pnl_ledger.jsonl"
    today = sa.datetime.now().date().isoformat()
    p.write_text(
        '{"timestamp": "%sT12:00:00", "pnl": -100}\n{"timestamp": "1999-01-01T12:00:00", "pnl": 999}\n'
        % today[:10],
        encoding="utf-8",
    )
    total = sa._today_realized_pnl_usd(tmp_path)
    assert total == -100.0
