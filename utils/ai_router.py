"""
AI Router - Smart task-to-model routing for cost efficiency.

Routing rules:
  GROK  → real-time news, X/Twitter sentiment, market events   (~$0.001/call, 2s)
  LOCAL → offline analysis, batch jobs, non-urgent reasoning   (FREE, 60-90s)
  OPENAI → structured JSON extraction, simple classification   (~$0.0002/call, 1s)
  CLAUDE → complex reasoning, code generation (not used in bot — via OpenClaw only)

Usage:
    from utils.ai_router import ask_ai
    result = ask_ai("news", prompt, ticker="AAPL")
    result = ask_ai("classify", prompt)
"""

import os
import json
import re
import logging
import requests
from pathlib import Path
from utils.local_llm import call_ollama

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parent.parent

def _load_env_key(name):
    val = os.getenv(name)
    if val:
        return val
    env_file = _ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return None


def _call_grok(prompt, max_tokens=100):
    """Call XAI Grok-3-mini. Returns text or None on failure."""
    api_key = _load_env_key("XAI_API_KEY")
    if not api_key:
        logger.warning("XAI_API_KEY not set — skipping Grok")
        return None
    try:
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        logger.info(f"Grok call OK | tokens≈{len(prompt.split())+len(text.split())} | ~$0.001")
        return text
    except Exception as e:
        logger.warning(f"Grok failed: {e}")
        return None


def _call_openai(prompt, max_tokens=200):
    """Call OpenAI gpt-4o-mini (cheapest structured model). Returns text or None."""
    api_key = _load_env_key("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping OpenAI")
        return None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        logger.info(f"OpenAI call OK | ~$0.0002")
        return text
    except Exception as e:
        logger.warning(f"OpenAI failed: {e}")
        return None


def ask_ai(task_type, prompt, ticker=None, max_tokens=150, fallback_to_local=True):
    """
    Route a prompt to the cheapest capable model for the task.

    task_type options:
      "news"      → Grok (real-time, $0.001) → Llama fallback
      "sentiment" → Grok (X/Twitter access)  → Llama fallback
      "classify"  → OpenAI gpt-4o-mini        → Llama fallback
      "analyze"   → Llama (free, no rush)
      "batch"     → Llama (free, offline OK)

    Returns: str response or None
    """
    label = f"[{ticker}] " if ticker else ""

    if task_type in ("news", "sentiment"):
        logger.info(f"{label}Routing to Grok (real-time task)")
        result = _call_grok(prompt, max_tokens=max_tokens)
        if result is None and fallback_to_local:
            logger.info(f"{label}Grok unavailable — falling back to Llama")
            result = call_ollama(prompt, timeout=90)
        return result

    elif task_type == "classify":
        logger.info(f"{label}Routing to OpenAI gpt-4o-mini (classification)")
        result = _call_openai(prompt, max_tokens=max_tokens)
        if result is None and fallback_to_local:
            logger.info(f"{label}OpenAI unavailable — falling back to Llama")
            result = call_ollama(prompt, timeout=60)
        return result

    else:  # "analyze", "batch", or anything else
        logger.info(f"{label}Routing to local Llama (free, offline task)")
        return call_ollama(prompt, timeout=90)


def parse_json_response(text):
    """Extract JSON from LLM response regardless of formatting."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return None
