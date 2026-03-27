import json
import re
import subprocess
from typing import Any

from utils.runtime_config import get_llm_config


def _llm_provider() -> str:
    try:
        cfg = get_llm_config() or {}
        return str(cfg.get("provider") or "none").strip().lower()
    except Exception:
        return "none"


def call_ollama(prompt: str, model: str = "llama3.1:8b", timeout: int = 60) -> str:
    """Call local Ollama model."""
    try:
        result = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Timeout (model too slow)"
    except Exception as e:
        return f"Error: {str(e)}"


def call_deepseek(prompt: str, *, timeout: int = 60) -> str:
    """
    Call DeepSeek using OpenAI-compatible chat endpoint.
    """
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
        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        return text or "Error: Empty DeepSeek response"
    except Exception as e:
        return f"Error: {str(e)}"


def call_llm(prompt: str, *, timeout: int = 60, model: str | None = None) -> str:
    """
    Provider-aware LLM caller.
    - none: short-circuit with disabled message
    - ollama: local model
    - deepseek: OpenAI-compatible DeepSeek endpoint
    """
    provider = _llm_provider()
    if provider == "none":
        return "Error: LLM provider disabled (provider=none)"
    if provider == "deepseek":
        return call_deepseek(prompt, timeout=timeout)

    cfg = get_llm_config() or {}
    chosen_model = model or str(cfg.get("default_model") or "llama3.1:8b").strip()
    return call_ollama(prompt, model=chosen_model, timeout=timeout)


def analyze_stock_drop(ticker: str, news_headlines: list[str], metrics: dict[str, Any]) -> dict[str, Any]:
    """Analyze if stock drop is unfair"""
    news_text = "\n".join([f"- {h}" for h in news_headlines]) if news_headlines else "No news"

    prompt = f"""Analyze: {ticker} dropped {metrics.get('drop_pct', 0):.1f}%
RSI: {metrics.get('rsi', 50):.1f}
News: {news_text}

Is this UNFAIR (overreaction) or FAIR (legitimate)?
Return JSON: {{"classification": "UNFAIR/FAIR", "confidence": 0.8, "reasoning": "why"}}"""

    response = call_llm(prompt, timeout=90)

    try:
        match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass

    return {"classification": "UNCERTAIN", "confidence": 0.5, "reasoning": "Parse error"}
