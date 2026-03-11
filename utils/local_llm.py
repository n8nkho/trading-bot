import json
import re
import logging
import requests

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"
_MAX_PROMPT_CHARS = 600   # Hard cap — controls token spend and latency
_MAX_TOKENS_FAST = 80     # Fast tasks (classify, sentiment fallback)
_MAX_TOKENS_DEEP = 150    # Analysis tasks

# Model tiers — use smallest capable model for each task
MODEL_FAST  = "llama3.2:1b"   # ~2s on ARM — sentiment, classify, quick checks
MODEL_MED   = "llama3.2:1b"  # 3b too slow on ARM   # ~5s on ARM — screening analysis
MODEL_DEEP  = "llama3.1:8b"   # ~25s on ARM — only for daily deep analysis


def call_ollama(prompt, model=MODEL_FAST, timeout=20, max_tokens=None):
    """
    Call local Ollama via HTTP API (non-blocking).
    Defaults: llama3.2:1b, 20s timeout, capped output.
    Returns text string or None on failure/timeout.
    """
    if len(prompt) > _MAX_PROMPT_CHARS:
        prompt = prompt[:_MAX_PROMPT_CHARS] + "..."

    n_predict = max_tokens or (_MAX_TOKENS_DEEP if model == MODEL_DEEP else _MAX_TOKENS_FAST)

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": n_predict,
                    "temperature": 0.1,
                    "stop": ["\n\n", "```"]
                }
            },
            timeout=timeout
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.exceptions.Timeout:
        logger.warning(f"Ollama timeout ({timeout}s) [{model}] — skipping")
        return None
    except Exception as e:
        logger.warning(f"Ollama error [{model}]: {e}")
        return None


def analyze_stock_drop(ticker, news_headlines, metrics):
    """Analyze if stock drop is an overreaction. Uses 3b for better reasoning."""
    top_news = "; ".join((h[:60] for h in (news_headlines or [])[:3])) or "no news"
    prompt = (
        f"{ticker} drop {metrics.get('drop_pct', 0):.1f}%, RSI {metrics.get('rsi', 50):.0f}. "
        f"News: {top_news}. "
        f'UNFAIR or FAIR? JSON: {{"classification":"UNFAIR/FAIR","confidence":0.8,"reasoning":"brief"}}'
    )
    response = call_ollama(prompt, model=MODEL_MED, timeout=20)
    if not response:
        return {"classification": "UNCERTAIN", "confidence": 0.5, "reasoning": "LLM unavailable"}
    try:
        match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {"classification": "UNCERTAIN", "confidence": 0.5, "reasoning": "Parse error"}
