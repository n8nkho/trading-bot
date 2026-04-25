from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.backtest_agent import BacktestAgent
from agents.cross_asset_agent import CROSS_ASSET_RELATIONSHIPS, CrossAssetAgent
from agents.earnings_intel_agent import EarningsIntelAgent
from agents.options_flow_agent import OptionsFlowAgent
from agents.prompt_evolution_agent import PromptEvolutionAgent
from agents.regime_detector import REGIMES, RegimeDetector
from agents.sentiment_velocity_agent import SentimentVelocityAgent


def test_imports_and_dry_runs():
    assert "TRENDING_BULL" in REGIMES
    assert RegimeDetector().detect_regime(dry_run=True)["regime"] in REGIMES
    assert CrossAssetAgent().run(dry_run=True)["overall_bias"] in {"BULLISH", "NEUTRAL", "BEARISH"}
    assert "total_trades" in BacktestAgent().run(dry_run=True)
    assert "symbols" in SentimentVelocityAgent().run(symbols=["AAPL"], dry_run=True)
    assert "signals" in OptionsFlowAgent().run(symbols=["AAPL"], dry_run=True)
    assert "entries" in EarningsIntelAgent().run(symbol="AAPL", dry_run=True)
    evo = PromptEvolutionAgent().run(dry_run=True, force=True)
    assert evo["triggered"] is True


def test_regime_classifier_logic():
    d = RegimeDetector()
    reg, _ = d._classify(
        {
            "spy_close": 530.0,
            "spy_ma20": 500.0,
            "vix": 40.0,
            "spy_1d_pct": -0.5,
            "avg_range_10d_pct": 2.0,
        }
    )
    assert reg == "CRISIS"


def test_sentiment_velocity_math():
    a = SentimentVelocityAgent()
    v = a._calculate_velocity({"2h": 0.4, "24h": 0.1, "7d": -0.2})
    assert round(v["velocity_2h_vs_24h"], 4) == 0.3
    assert round(v["velocity_24h_vs_7d"], 4) == 0.3
    assert round(v["acceleration"], 4) == 0.0


def test_backtest_metrics_with_mock_data(tmp_path, monkeypatch):
    import agents.backtest_agent as bt

    trade_path = tmp_path / "trade_history.json"
    ref_path = tmp_path / "reflection_log.json"
    out_path = tmp_path / "backtest_results.json"
    trade_path.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "ticker": "AAPL",
                        "closed_at": "2026-04-20T12:00:00+00:00",
                        "pnl_pct_fraction": 0.05,
                        "critique_verdict": "CONFIRM",
                        "indicators": {"rsi": 45, "volume_ratio": 1.4, "macd": "bullish", "trend_score": 80},
                    },
                    {
                        "ticker": "TSLA",
                        "closed_at": "2026-04-21T12:00:00+00:00",
                        "pnl_pct_fraction": -0.03,
                        "critique_verdict": "REJECT",
                        "indicators": {"rsi": 62, "volume_ratio": 0.9, "macd": "bearish", "trend_score": 30},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    ref_path.write_text(json.dumps({"records": [{"score": 7}, {"score": 5}]}), encoding="utf-8")
    monkeypatch.setattr(bt, "_TRADES", trade_path)
    monkeypatch.setattr(bt, "_REFLECT", ref_path)
    monkeypatch.setattr(bt, "_RESULTS", out_path)
    out = bt.BacktestAgent().run(dry_run=True)
    assert out["total_trades"] == 2
    assert "delta" in out


def test_prompt_evolution_trigger_threshold():
    p = PromptEvolutionAgent()
    rows = [{"score": 5.9}, {"score": 5.5}, {"score": 5.8}]
    trig, avg = p._should_trigger(rows)
    assert trig is True
    assert avg < 6.0


def test_cross_asset_relationship_mapping():
    assert "TLT" in CROSS_ASSET_RELATIONSHIPS
    assert "rising" in CROSS_ASSET_RELATIONSHIPS["TLT"]
    ca = CrossAssetAgent()
    assert ca._state(0.6) == "RISING"
    assert ca._state(-0.6) == "FALLING"
    assert ca._state(0.0) == "NEUTRAL"


def test_seed_files_valid_json():
    root = Path(__file__).resolve().parent.parent
    must = [
        root / "data" / "sentiment_velocity.json",
        root / "data" / "earnings_intel.json",
        root / "data" / "options_flow.json",
        root / "data" / "cross_asset_signal.json",
        root / "data" / "backtest_results.json",
        root / "data" / "prompt_store.json",
    ]
    for p in must:
        assert p.exists(), str(p)
        json.loads(p.read_text(encoding="utf-8"))
