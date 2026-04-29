"""
Central LLM router: DeepSeek + xAI (Grok), timeouts, global rate limit (10/min), fallback.
API keys from environment only.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Literal

from utils.cost_calculator import track_api_cost
from utils.runtime_config import get_llm_config

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOTENV_LOADED = False

_MAX_PER_MINUTE = 10
_WINDOW_SEC = 60.0
_DEFAULT_TIMEOUT = 30
_lock = threading.Lock()
_call_times: deque[float] = deque()


def normalize_xai_api_key(raw: str) -> str:
    """xAI Grok keys are issued as `xai-…`; `.env` sometimes stores only the bare segment."""
    k = (raw or "").strip().strip('"').strip("'")
    if not k:
        return ""
    # Cron/scripts sometimes prepend twice after merges — collapse `xai-xai-…` → `xai-…`.
    while k.lower().startswith("xai-xai-"):
        k = k[4:]
    if k.lower().startswith("xai-"):
        return k
    if len(k) >= 20 and re.fullmatch(r"[A-Za-z0-9_-]+", k):
        return "xai-" + k
    return k


def _load_repo_dotenv() -> None:
    """Load repo .env files before reading API keys.

    Primary `.env` uses override=True so a stale XAI/DeepSeek value injected by cron,
    systemd, or `export` in a wrapper cannot beat the on-disk file (common VM footgun).
    `.env.fortress` stays override=False so explicit process env can override flags.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO_ROOT / ".env", override=True)
        load_dotenv(_REPO_ROOT / ".env.fortress", override=False)
    except Exception:
        pass
    _DOTENV_LOADED = True


def ensure_llm_env_loaded() -> None:
    """Load repo `.env` / `.env.fortress` using the same rules as LLMRouter (for non-router callers)."""
    _load_repo_dotenv()


def _acquire_rate_slot() -> None:
    now = time.monotonic()
    with _lock:
        while _call_times and now - _call_times[0] > _WINDOW_SEC:
            _call_times.popleft()
        if len(_call_times) >= _MAX_PER_MINUTE:
            wait = _WINDOW_SEC - (now - _call_times[0]) + 0.05
        else:
            wait = 0.0
    if wait > 0:
        time.sleep(wait)
        now = time.monotonic()
        with _lock:
            while _call_times and now - _call_times[0] > _WINDOW_SEC:
                _call_times.popleft()
    with _lock:
        _call_times.append(time.monotonic())


def _openai_style_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    user_prompt: str,
    system_prompt: str,
    max_tokens: int,
    timeout: int,
    cost_service: str,
) -> str:
    _acquire_rate_slot()
    try:
        from openai import OpenAI
    except Exception as e:
        return f"Error: openai package missing ({e})"
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        try:
            usage = getattr(resp, "usage", None)
            pt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
            ct = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
            track_api_cost(
                service=cost_service,
                model=model,
                input_tokens=pt,
                output_tokens=ct,
                cached_tokens=0,
            )
        except Exception:
            pass
        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        return text or "Error: empty response"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


class LLMRouter:
    def call_deepseek(self, prompt: str, system_prompt: str = "", *, max_tokens: int = 1000) -> str:
        _load_repo_dotenv()
        cfg = get_llm_config() or {}
        key = str(cfg.get("deepseek_api_key") or os.getenv("DEEPSEEK_API_KEY") or "").strip()
        if not key:
            return "Error: Missing DEEPSEEK_API_KEY"
        base = str(cfg.get("deepseek_base_url") or "https://api.deepseek.com/v1").strip()
        model = str(cfg.get("deepseek_model") or cfg.get("default_model") or "deepseek-chat").strip()
        return _openai_style_chat(
            api_key=key,
            base_url=base,
            model=model,
            user_prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            timeout=_DEFAULT_TIMEOUT,
            cost_service="deepseek",
        )

    def call_xai(self, prompt: str, system_prompt: str = "", *, max_tokens: int = 1000) -> str:
        _load_repo_dotenv()
        key = normalize_xai_api_key(str(os.getenv("XAI_API_KEY") or ""))
        if not key:
            return "Error: Missing XAI_API_KEY"
        model = str(os.getenv("XAI_MODEL") or "grok-3").strip()
        return _openai_style_chat(
            api_key=key,
            base_url="https://api.x.ai/v1",
            model=model,
            user_prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            timeout=_DEFAULT_TIMEOUT,
            cost_service="xai",
        )

    def call_with_fallback(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        primary: Literal["deepseek", "xai"] = "deepseek",
        max_tokens: int = 1000,
    ) -> str:
        order = [primary, "xai" if primary == "deepseek" else "deepseek"]
        last = ""
        for p in order:
            if p == "deepseek":
                out = self.call_deepseek(prompt, system_prompt, max_tokens=max_tokens)
            else:
                out = self.call_xai(prompt, system_prompt, max_tokens=max_tokens)
            last = out
            if out and not str(out).startswith("Error:"):
                return out
        return last or "Error: all providers failed"
