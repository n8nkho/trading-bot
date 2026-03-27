from __future__ import annotations

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import local_llm


class TestLocalLlmProvider(unittest.TestCase):
    def test_none_provider_short_circuits(self):
        with patch.object(local_llm, "get_llm_config", return_value={"provider": "none"}):
            out = local_llm.call_llm("hello")
            self.assertIn("provider=none", out)

    def test_deepseek_missing_key(self):
        with patch.object(local_llm, "get_llm_config", return_value={"provider": "deepseek"}):
            out = local_llm.call_llm("hello")
            self.assertIn("Missing DEEPSEEK_API_KEY", out)


if __name__ == "__main__":
    unittest.main()

