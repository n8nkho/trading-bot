from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import local_llm


class _FakeUsage:
    prompt_tokens = 120
    completion_tokens = 30


class _FakeMsg:
    content = "OK"


class _FakeChoice:
    message = _FakeMsg()


class _FakeResp:
    choices = [_FakeChoice()]
    usage = _FakeUsage()


class _FakeCompletions:
    @staticmethod
    def create(**kwargs):
        return _FakeResp()


class _FakeChat:
    completions = _FakeCompletions()


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.chat = _FakeChat()


class TestDeepseekCostTracking(unittest.TestCase):
    def test_tracks_cost_when_usage_present(self):
        with patch.object(
            local_llm,
            "get_llm_config",
            return_value={
                "provider": "deepseek",
                "deepseek_api_key": "k",
                "deepseek_base_url": "https://api.deepseek.com/v1",
                "deepseek_model": "deepseek-chat",
            },
        ), patch.dict("sys.modules", {"openai": type("m", (), {"OpenAI": _FakeClient})}), patch.object(
            local_llm, "track_api_cost"
        ) as tracker:
            out = local_llm.call_deepseek("hello", timeout=5)
            self.assertEqual(out, "OK")
            tracker.assert_called_once()
            kwargs = tracker.call_args.kwargs
            self.assertEqual(kwargs.get("service"), "deepseek")
            self.assertEqual(kwargs.get("model"), "deepseek-chat")
            self.assertEqual(kwargs.get("input_tokens"), 120)
            self.assertEqual(kwargs.get("output_tokens"), 30)


if __name__ == "__main__":
    unittest.main()

