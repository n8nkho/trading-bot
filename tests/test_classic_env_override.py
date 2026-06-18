"""Classic .env must override inherited Fortress/shell Alpaca keys."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dotenv import load_dotenv


class TestClassicEnvOverride(unittest.TestCase):
    def test_load_dotenv_override_replaces_inherited_alpaca_key(self):
        with tempfile.TemporaryDirectory() as td:
            env_path = Path(td) / ".env"
            env_path.write_text("ALPACA_API_KEY=CLASSIC_BOOK_KEY\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"ALPACA_API_KEY": "FORTRESS_BOOK_KEY"}, clear=False):
                load_dotenv(env_path, override=False)
                self.assertEqual(os.environ.get("ALPACA_API_KEY"), "FORTRESS_BOOK_KEY")
                load_dotenv(env_path, override=True)
                self.assertEqual(os.environ.get("ALPACA_API_KEY"), "CLASSIC_BOOK_KEY")


if __name__ == "__main__":
    unittest.main()
