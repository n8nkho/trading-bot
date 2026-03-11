import subprocess
import json
import re

def call_ollama(prompt, model="llama3.1:8b", timeout=60):
    """Call local Ollama model - increased timeout for ARM CPU"""
    try:
        result = subprocess.run(
            ['ollama', 'run', model, prompt],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Timeout (model too slow)"
    except Exception as e:
        return f"Error: {str(e)}"

def analyze_stock_drop(ticker, news_headlines, metrics):
    """Analyze if stock drop is unfair"""
    news_text = "\n".join([f"- {h}" for h in news_headlines]) if news_headlines else "No news"
    
    prompt = f"""Analyze: {ticker} dropped {metrics.get('drop_pct', 0):.1f}%
RSI: {metrics.get('rsi', 50):.1f}
News: {news_text}

Is this UNFAIR (overreaction) or FAIR (legitimate)?
Return JSON: {{"classification": "UNFAIR/FAIR", "confidence": 0.8, "reasoning": "why"}}"""

    response = call_ollama(prompt, model="llama3.1:8b", timeout=90)
    
    try:
        match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    
    return {"classification": "UNCERTAIN", "confidence": 0.5, "reasoning": "Parse error"}
