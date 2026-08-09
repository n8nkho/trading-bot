"""DeepSeek LLM helpers for Classic Fortress (no local Llama/Ollama)."""
from __future__ import annotations

import json
import re
from typing import Any

from utils.cost_calculator import track_api_cost
from utils.runtime_config import get_llm_config


def _llm_provider() -> str:
    try:
        cfg = get_llm_config() or {}
        return str(cfg.get("provider") or "none").strip().lower()
    except Exception:
        return "none"


def call_deepseek(prompt: str, *, timeout: int = 60) -> str:
    """Call DeepSeek using OpenAI-compatible chat endpoint."""
    try:
        from utils.llm_router import ensure_llm_env_loaded

        ensure_llm_env_loaded()
    except Exception:
        pass
    cfg = get_llm_config() or {}
    api_key = cfg.get("deepseek_api_key") or None
    if not api_key:
        import os

        api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "Error: Missing DEEPSEEK_API_KEY"
    try:
        from openai import OpenAI
    except Exception:
        return "Error: openai package not installed"
    base_url = str(cfg.get("deepseek_base_url") or "https://api.deepseek.com/v1").strip()
    model = str(cfg.get("deepseek_model") or cfg.get("default_model") or "deepseek-chat").strip()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300,
        )
        try:
            usage = getattr(resp, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage is not None else 0
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0) if usage is not None else 0
            track_api_cost(
                service="deepseek",
                model=model,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                cached_tokens=0,
            )
        except Exception:
            pass
        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        return text or "Error: Empty DeepSeek response"
    except Exception as e:
        return f"Error: {str(e)}"


def call_llm(prompt: str, *, timeout: int = 60, model: str | None = None) -> str:
    """Provider-aware LLM caller — DeepSeek only (local Llama/Ollama removed)."""
    del model  # DeepSeek model comes from runtime config / env
    provider = _llm_provider()
    if provider == "none":
        return "Error: LLM provider disabled (provider=none)"
    if provider == "deepseek":
        return call_deepseek(prompt, timeout=timeout)
    if provider == "ollama":
        return "Error: Ollama/Llama removed — set llm.provider=deepseek"
    return f"Error: Unsupported LLM provider '{provider}' (use deepseek or none)"


def analyze_stock_drop(ticker: str, news_headlines: list[str], metrics: dict[str, Any]) -> dict[str, Any]:
    """Analyze if stock drop is unfair."""
    news_text = "\n".join([f"- {h}" for h in news_headlines]) if news_headlines else "No news"

    prompt = f"""Analyze: {ticker} dropped {metrics.get('drop_pct', 0):.1f}%
RSI: {metrics.get('rsi', 50):.1f}
News: {news_text}

Is this UNFAIR (overreaction) or FAIR (legitimate)?
Return JSON: {{"classification": "UNFAIR/FAIR", "confidence": 0.8, "reasoning": "why"}}"""

    response = call_llm(prompt, timeout=90)
    if str(response or "").strip().startswith("Error:"):
        return {
            "classification": "UNCERTAIN",
            "confidence": 0.5,
            "reasoning": str(response).strip()[:200],
        }

    try:
        match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass

    return {
        "classification": "UNCERTAIN",
        "confidence": 0.5,
        "reasoning": f"Parse error (LLM response not JSON: {(response or '')[:120]})",
    }
