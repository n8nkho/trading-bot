#!/usr/bin/env python3
"""
Quick LLM provider diagnostics without mandatory paid API calls.

Usage:
  python3 scripts/check_llm_provider.py
  python3 scripts/check_llm_provider.py --ping
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.local_llm import call_llm
from utils.runtime_config import get_llm_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ping", action="store_true", help="Send a tiny prompt to configured provider")
    args = parser.parse_args()

    cfg = get_llm_config() or {}
    provider = str(cfg.get("provider") or "none").strip().lower()
    model = str(cfg.get("default_model") or "").strip()
    print(f"provider={provider}")
    print(f"default_model={model}")

    if provider == "deepseek":
        has_key = bool(cfg.get("deepseek_api_key")) or bool(__import__("os").getenv("DEEPSEEK_API_KEY"))
        print(f"deepseek_key_present={has_key}")

    if not args.ping:
        print("No API call made. Use --ping to test live response.")
        return 0

    resp = call_llm("Reply with exactly: OK", timeout=20)
    print(f"ping_response={resp[:200]}")
    return 0 if "OK" in resp else 1


if __name__ == "__main__":
    raise SystemExit(main())

