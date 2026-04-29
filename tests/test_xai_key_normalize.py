"""xAI API keys must be passed as xai-…; .env may omit the prefix."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.llm_router import normalize_xai_api_key


def test_prepends_xai_prefix_when_missing() -> None:
    assert normalize_xai_api_key("Jrvg7LvK5KHm4mFFexg0").startswith("xai-Jrvg7")


def test_preserves_full_prefix() -> None:
    assert normalize_xai_api_key("xai-Jrvg7LvK5KHm4mFFexg0") == "xai-Jrvg7LvK5KHm4mFFexg0"


def test_strips_quotes() -> None:
    assert normalize_xai_api_key('"Jrvg7LvK5KHm4mFFexg0"').startswith("xai-Jrvg7")


def test_collapses_double_xai_prefix() -> None:
    bare = "Jrvg7LvK5KHm4mFFexg0"
    doubled = "xai-xai-" + bare
    assert normalize_xai_api_key(doubled) == normalize_xai_api_key("xai-" + bare)
