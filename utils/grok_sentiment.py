import os
import requests
import logging
from datetime import datetime
from pathlib import Path

# Setup logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "grok.log"

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

def check_twitter_sentiment(ticker, confidence_threshold=0.8):
    """
    Check Twitter sentiment using Grok API (minimal usage to save costs).
    
    Args:
        ticker: Stock ticker symbol
        confidence_threshold: Only call API if confidence > this (default 0.8)
    
    Returns:
        "BULLISH", "BEARISH", "NEUTRAL", or None if API key missing
    """
    # Check if API key exists
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        logging.info(f"Skipped Grok call for {ticker} - no API key")
        return None
    
    # Only call if confidence threshold met (saves money)
    if confidence_threshold <= 0.8:
        logging.info(f"Skipped Grok call for {ticker} - confidence threshold not met")
        return None
    
    # Very short prompt to minimize tokens
    prompt = f"Twitter sentiment ${ticker} last hour: BULLISH/BEARISH/NEUTRAL? One word."
    
    try:
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "grok-3-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "temperature": 0.1
            },
            timeout=10
        )
        
        response.raise_for_status()
        result = response.json()
        
        # Extract sentiment
        sentiment = result["choices"][0]["message"]["content"].strip().upper()
        
        # Normalize response
        if "BULLISH" in sentiment:
            sentiment = "BULLISH"
        elif "BEARISH" in sentiment:
            sentiment = "BEARISH"
        elif "NEUTRAL" in sentiment:
            sentiment = "NEUTRAL"
        else:
            sentiment = "NEUTRAL"  # Default if unclear
        
        # Log call with cost tracking (~$0.001 per call)
        logging.info(f"Grok call: {ticker} -> {sentiment} | Cost: ~$0.001")
        
        return sentiment
        
    except requests.exceptions.Timeout:
        logging.error(f"Grok timeout for {ticker}")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Grok API error for {ticker}: {str(e)}")
        return None
    except (KeyError, IndexError) as e:
        logging.error(f"Grok response parse error for {ticker}: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error for {ticker}: {str(e)}")
        return None
