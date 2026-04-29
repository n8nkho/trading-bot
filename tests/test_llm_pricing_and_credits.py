"""xAI cost resolution + llm_credits snapshot shape (no network)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_resolve_xai_grok3():
    from utils.cost_calculator import _resolve_pricing_row

    svc, mk, pricing = _resolve_pricing_row("xai", "grok-3")
    assert svc == "xai"
    assert mk in ("grok-3", "grok-3-mini", "grok-mini")
    assert "input" in pricing


def test_track_api_cost_xai_writes(tmp_path, monkeypatch):
    from utils import cost_calculator

    monkeypatch.setattr(cost_calculator, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cost_calculator, "API_COSTS_FILE", tmp_path / "api_costs.jsonl")
    rec = cost_calculator.track_api_cost("xai", "grok-3", 1_000_000, 500_000, 0)
    assert rec["service"] == "xai"
    assert rec["model"] == "grok-3"
    assert rec["cost_with_cache"] > 0
