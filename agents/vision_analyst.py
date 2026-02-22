"""
Vision Analyst Agent
Uses Claude's vision capabilities to analyze stock charts for technical patterns
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import pandas as pd
import numpy as np
from anthropic import Anthropic

# Setup logging
logger = logging.getLogger(__name__)

# Configuration
CHART_DIR = Path("/tmp/trading_charts")
CHART_DIR.mkdir(exist_ok=True)
COST_LOG_FILE = Path("logs/api_costs.log")
COST_LOG_FILE.parent.mkdir(exist_ok=True)

# Cost tracking (with prompt caching, costs are much lower)
VISION_COST_PER_IMAGE = 0.02  # Base cost without caching
CACHE_WRITE_COST_PER_TOKEN = 0.00000375  # Cost to write to cache
CACHE_READ_COST_PER_TOKEN = 0.0000003  # Cost to read from cache (90% savings!)
INPUT_TOKEN_COST = 0.000003  # Regular input token cost
OUTPUT_TOKEN_COST = 0.000015  # Output token cost

# Initialize Anthropic client
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
anthropic_client = None

if ANTHROPIC_API_KEY:
    try:
        anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
        logger.info("Anthropic client initialized for vision analysis")
    except Exception as e:
        logger.error(f"Failed to initialize Anthropic client: {e}")
else:
    logger.warning("ANTHROPIC_API_KEY not found. Vision analysis disabled.")


def calculate_rsi(prices, period=14):
    """Calculate RSI indicator."""
    deltas = np.diff(prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum()/period
    down = -seed[seed < 0].sum()/period
    rs = up/down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100./(1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i-1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta

        up = (up*(period-1) + upval)/period
        down = (down*(period-1) + downval)/period
        rs = up/down if down != 0 else 0
        rsi[i] = 100. - 100./(1. + rs)

    return rsi


def screenshot_chart(ticker, timeframe='1d', period='3mo'):
    """
    Create a technical chart with candlesticks, volume, and RSI.
    
    Args:
        ticker: Stock symbol
        timeframe: Data interval ('1m', '5m', '1h', '1d', '1wk')
        period: Historical period ('1d', '5d', '1mo', '3mo', '1y')
        
    Returns:
        str: Path to saved chart image, or None if error
    """
    try:
        logger.info(f"{ticker}: Creating {timeframe} chart for {period} period")
        
        # Download data
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=timeframe)
        
        if df.empty:
            logger.error(f"{ticker}: No data available for {timeframe}/{period}")
            return None
        
        # Calculate RSI
        rsi = calculate_rsi(df['Close'].values)
        
        # Create figure with 3 subplots
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), 
                                            gridspec_kw={'height_ratios': [3, 1, 1]})
        fig.suptitle(f'{ticker} - {timeframe} Chart', fontsize=16, fontweight='bold')
        
        # Plot 1: Candlestick chart
        for idx in range(len(df)):
            date = df.index[idx]
            open_price = df['Open'].iloc[idx]
            close_price = df['Close'].iloc[idx]
            high_price = df['High'].iloc[idx]
            low_price = df['Low'].iloc[idx]
            
            color = 'green' if close_price >= open_price else 'red'
            
            # Draw high-low line
            ax1.plot([date, date], [low_price, high_price], color=color, linewidth=1)
            
            # Draw candlestick body
            height = abs(close_price - open_price)
            bottom = min(open_price, close_price)
            rect = Rectangle((mdates.date2num(date) - 0.3, bottom), 0.6, height,
                           facecolor=color, edgecolor=color, alpha=0.8)
            ax1.add_patch(rect)
        
        ax1.set_ylabel('Price ($)', fontsize=12)
        ax1.grid(True, alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        
        # Add moving averages
        if len(df) >= 20:
            ma20 = df['Close'].rolling(window=20).mean()
            ax1.plot(df.index, ma20, label='MA20', color='blue', linewidth=1.5, alpha=0.7)
        if len(df) >= 50:
            ma50 = df['Close'].rolling(window=50).mean()
            ax1.plot(df.index, ma50, label='MA50', color='orange', linewidth=1.5, alpha=0.7)
        
        ax1.legend(loc='upper left')
        
        # Plot 2: Volume
        colors = ['green' if df['Close'].iloc[i] >= df['Open'].iloc[i] else 'red' 
                 for i in range(len(df))]
        ax2.bar(df.index, df['Volume'], color=colors, alpha=0.6)
        ax2.set_ylabel('Volume', fontsize=12)
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        
        # Plot 3: RSI
        ax3.plot(df.index, rsi, color='purple', linewidth=2)
        ax3.axhline(y=70, color='r', linestyle='--', alpha=0.5, label='Overbought (70)')
        ax3.axhline(y=30, color='g', linestyle='--', alpha=0.5, label='Oversold (30)')
        ax3.fill_between(df.index, 30, 70, alpha=0.1, color='gray')
        ax3.set_ylabel('RSI', fontsize=12)
        ax3.set_xlabel('Date', fontsize=12)
        ax3.set_ylim(0, 100)
        ax3.grid(True, alpha=0.3)
        ax3.legend(loc='upper left', fontsize=8)
        ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        
        # Rotate x-axis labels
        for ax in [ax1, ax2, ax3]:
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        plt.tight_layout()
        
        # Save chart
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{ticker}_{timeframe}_{timestamp}.png"
        filepath = CHART_DIR / filename
        
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        logger.info(f"{ticker}: Chart saved to {filepath}")
        return str(filepath)
        
    except Exception as e:
        logger.error(f"{ticker}: Error creating chart: {type(e).__name__}: {str(e)}")
        return None


def analyze_chart_with_vision(ticker, chart_path):
    """
    Analyze a chart image using Claude's vision capabilities with prompt caching.
    
    Args:
        ticker: Stock symbol
        chart_path: Path to chart image
        
    Returns:
        dict: {
            'success': bool,
            'analysis': dict with findings,
            'raw_response': str,
            'cost': float,
            'cache_savings': float,
            'error': str or None
        }
    """
    if not anthropic_client:
        logger.error(f"{ticker}: Anthropic client not initialized")
        return {
            'success': False,
            'analysis': None,
            'raw_response': None,
            'cost': 0,
            'cache_savings': 0,
            'error': 'Anthropic client not initialized'
        }
    
    try:
        logger.info(f"{ticker}: Analyzing chart with Claude Vision (with caching): {chart_path}")
        
        # Read image file
        with open(chart_path, 'rb') as f:
            image_data = f.read()
        
        import base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # System prompt with cache_control - this gets cached and reused!
        system_prompt = """You are an expert technical analyst specializing in stock chart analysis.

Your task is to analyze stock charts and provide detailed technical analysis covering:

1. **Support and Resistance Levels**: Identify key price levels where the stock has historically bounced or faced selling pressure.

2. **Chart Patterns**: Recognize patterns such as:
   - Head and shoulders (bullish/bearish)
   - Double top/bottom
   - Triangles (ascending/descending/symmetrical)
   - Flags and pennants
   - Cup and handle
   - Wedges

3. **Trend Analysis**:
   - Current trend direction (uptrend/downtrend/sideways)
   - Trend strength (strong/moderate/weak)
   - Moving average alignment

4. **Technical Indicators**:
   - RSI interpretation (overbought/oversold/neutral)
   - Volume analysis (increasing/decreasing/normal)
   - Any divergences between price and indicators

5. **Entry and Exit Points**:
   - Optimal entry price levels
   - Stop loss recommendations
   - Take profit targets

6. **Overall Assessment**:
   - Bullish, bearish, or neutral outlook
   - Confidence level (high/medium/low)
   - Key risks or concerns

Always return your analysis as a valid JSON object with this exact structure:
{
    "support_levels": [list of price levels as numbers],
    "resistance_levels": [list of price levels as numbers],
    "patterns": [
        {"name": "pattern name", "type": "bullish/bearish", "confidence": "high/medium/low"}
    ],
    "trend": {
        "direction": "uptrend/downtrend/sideways",
        "strength": "strong/moderate/weak"
    },
    "rsi_status": "overbought/oversold/neutral",
    "volume_trend": "increasing/decreasing/normal",
    "entry_points": [list of recommended entry prices as numbers],
    "stop_loss": price level as number,
    "take_profit": [list of target prices as numbers],
    "outlook": "bullish/bearish/neutral",
    "confidence": "high/medium/low",
    "summary": "brief summary of key findings"
}"""
        
        # Call Claude Vision API with prompt caching
        message = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}  # Cache this system prompt!
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": f"Analyze this stock chart for {ticker} and provide your technical analysis in the JSON format specified."
                        }
                    ]
                }
            ]
        )
        
        # Extract response
        response_text = message.content[0].text
        
        # Calculate costs with caching
        usage = message.usage
        input_tokens = getattr(usage, 'input_tokens', 0)
        output_tokens = getattr(usage, 'output_tokens', 0)
        cache_creation_tokens = getattr(usage, 'cache_creation_input_tokens', 0)
        cache_read_tokens = getattr(usage, 'cache_read_input_tokens', 0)
        
        # Calculate actual cost
        cache_write_cost = cache_creation_tokens * CACHE_WRITE_COST_PER_TOKEN
        cache_read_cost = cache_read_tokens * CACHE_READ_COST_PER_TOKEN
        regular_input_cost = (input_tokens - cache_read_tokens) * INPUT_TOKEN_COST
        output_cost = output_tokens * OUTPUT_TOKEN_COST
        
        total_cost = cache_write_cost + cache_read_cost + regular_input_cost + output_cost
        
        # Calculate savings (what it would have cost without caching)
        cost_without_cache = input_tokens * INPUT_TOKEN_COST + output_cost
        cache_savings = cost_without_cache - total_cost
        savings_pct = (cache_savings / cost_without_cache * 100) if cost_without_cache > 0 else 0
        
        # Log cost details
        log_api_cost(ticker, 'vision_analysis', {
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_creation_tokens': cache_creation_tokens,
            'cache_read_tokens': cache_read_tokens,
            'total_cost': total_cost,
            'cache_savings': cache_savings,
            'savings_pct': savings_pct
        })
        
        logger.info(f"{ticker}: Vision analysis complete - Cost: ${total_cost:.4f} (saved ${cache_savings:.4f}, {savings_pct:.1f}%)")
        if cache_read_tokens > 0:
            logger.info(f"{ticker}: ✓ Cache hit! Read {cache_read_tokens} tokens from cache")
        elif cache_creation_tokens > 0:
            logger.info(f"{ticker}: ⚡ Cache created with {cache_creation_tokens} tokens (future calls will be 90% cheaper!)")
        
        # Try to parse JSON from response
        try:
            # Find JSON in response (might be wrapped in markdown code blocks)
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response_text
            
            analysis = json.loads(json_str)
            
        except json.JSONDecodeError as e:
            logger.warning(f"{ticker}: Could not parse JSON from response: {e}")
            # Return raw response if JSON parsing fails
            analysis = {
                'raw_analysis': response_text,
                'parse_error': str(e)
            }
        
        return {
            'success': True,
            'analysis': analysis,
            'raw_response': response_text,
            'cost': total_cost,
            'cache_savings': cache_savings,
            'savings_pct': savings_pct,
            'error': None
        }
        
    except Exception as e:
        logger.error(f"{ticker}: Error in vision analysis: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'analysis': None,
            'raw_response': None,
            'cost': 0,
            'cache_savings': 0,
            'savings_pct': 0,
            'error': f"{type(e).__name__}: {str(e)}"
        }


def log_api_cost(ticker, api_type, cost_data):
    """
    Log API costs to file for tracking.
    
    Args:
        ticker: Stock symbol
        api_type: Type of API call (e.g., 'vision_analysis')
        cost_data: Dict with cost breakdown
    """
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            'timestamp': timestamp,
            'ticker': ticker,
            'api_type': api_type,
            **cost_data
        }
        
        with open(COST_LOG_FILE, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
            
    except Exception as e:
        logger.error(f"Failed to log API cost: {e}")


def multi_timeframe_analysis(ticker):
    """
    Perform multi-timeframe analysis using Claude Vision.
    
    Analyzes 4 timeframes: 5min, 1hour, daily, weekly
    Identifies alignment or conflicts across timeframes.
    
    Args:
        ticker: Stock symbol
        
    Returns:
        dict: {
            'success': bool,
            'timeframes': {
                '5min': analysis dict,
                '1hour': analysis dict,
                'daily': analysis dict,
                'weekly': analysis dict
            },
            'alignment': {
                'all_bullish': bool,
                'all_bearish': bool,
                'mixed': bool,
                'summary': str
            },
            'total_cost': float,
            'error': str or None
        }
    """
    logger.info(f"{ticker}: Starting multi-timeframe analysis")
    
    timeframes = [
        ('5min', '5m', '1d'),   # 5-minute chart, 1 day of data
        ('1hour', '1h', '5d'),  # 1-hour chart, 5 days of data
        ('daily', '1d', '3mo'), # Daily chart, 3 months of data
        ('weekly', '1wk', '1y') # Weekly chart, 1 year of data
    ]
    
    results = {}
    total_cost = 0
    total_savings = 0
    errors = []
    
    for name, interval, period in timeframes:
        logger.info(f"{ticker}: Analyzing {name} timeframe...")
        
        # Create chart
        chart_path = screenshot_chart(ticker, timeframe=interval, period=period)
        
        if not chart_path:
            logger.error(f"{ticker}: Failed to create {name} chart")
            errors.append(f"Failed to create {name} chart")
            results[name] = None
            continue
        
        # Analyze with vision
        analysis = analyze_chart_with_vision(ticker, chart_path)
        
        if analysis['success']:
            results[name] = analysis
            total_cost += analysis['cost']
            total_savings += analysis.get('cache_savings', 0)
            logger.info(f"{ticker}: {name} analysis complete (cost: ${analysis['cost']:.4f}, saved: ${analysis.get('cache_savings', 0):.4f})")
        else:
            logger.error(f"{ticker}: {name} analysis failed: {analysis['error']}")
            errors.append(f"{name}: {analysis['error']}")
            results[name] = None
    
    # Analyze alignment across timeframes
    alignment = analyze_timeframe_alignment(results)
    
    total_savings_pct = (total_savings / (total_cost + total_savings) * 100) if (total_cost + total_savings) > 0 else 0
    
    logger.info(f"{ticker}: Multi-timeframe analysis complete - Total cost: ${total_cost:.4f}, Total savings: ${total_savings:.4f} ({total_savings_pct:.1f}%)")
    
    return {
        'success': len(errors) == 0,
        'timeframes': results,
        'alignment': alignment,
        'total_cost': total_cost,
        'total_savings': total_savings,
        'savings_pct': total_savings_pct,
        'errors': errors if errors else None
    }


def analyze_timeframe_alignment(timeframe_results):
    """
    Analyze alignment across multiple timeframes.
    
    Args:
        timeframe_results: Dict of timeframe analyses
        
    Returns:
        dict: Alignment analysis
    """
    outlooks = []
    
    for name, result in timeframe_results.items():
        if result and result['success'] and result['analysis']:
            outlook = result['analysis'].get('outlook', 'neutral')
            outlooks.append((name, outlook))
    
    if not outlooks:
        return {
            'all_bullish': False,
            'all_bearish': False,
            'mixed': True,
            'summary': 'No valid analyses available'
        }
    
    bullish_count = sum(1 for _, outlook in outlooks if outlook == 'bullish')
    bearish_count = sum(1 for _, outlook in outlooks if outlook == 'bearish')
    neutral_count = sum(1 for _, outlook in outlooks if outlook == 'neutral')
    
    all_bullish = bullish_count == len(outlooks)
    all_bearish = bearish_count == len(outlooks)
    mixed = not (all_bullish or all_bearish)
    
    # Generate summary
    if all_bullish:
        summary = f"✓ STRONG ALIGNMENT: All {len(outlooks)} timeframes are BULLISH"
    elif all_bearish:
        summary = f"✗ STRONG ALIGNMENT: All {len(outlooks)} timeframes are BEARISH"
    elif bullish_count > bearish_count:
        summary = f"⚠ MIXED: {bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral - Bullish bias"
    elif bearish_count > bullish_count:
        summary = f"⚠ MIXED: {bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral - Bearish bias"
    else:
        summary = f"⚠ MIXED: {bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral - No clear bias"
    
    return {
        'all_bullish': all_bullish,
        'all_bearish': all_bearish,
        'mixed': mixed,
        'bullish_count': bullish_count,
        'bearish_count': bearish_count,
        'neutral_count': neutral_count,
        'summary': summary,
        'timeframe_outlooks': outlooks
    }


def quick_vision_check(ticker, confidence):
    """
    Quick vision check for high-confidence candidates.
    Uses daily chart only to save costs.
    
    Args:
        ticker: Stock symbol
        confidence: Current confidence score
        
    Returns:
        dict: {
            'vision_approved': bool,
            'adjusted_confidence': float,
            'analysis': dict or None,
            'cost': float,
            'reason': str
        }
    """
    logger.info(f"{ticker}: Running quick vision check (confidence: {confidence:.2f})")
    
    # Create daily chart
    chart_path = screenshot_chart(ticker, timeframe='1d', period='3mo')
    
    if not chart_path:
        logger.error(f"{ticker}: Failed to create chart for vision check")
        return {
            'vision_approved': False,
            'adjusted_confidence': confidence,
            'analysis': None,
            'cost': 0,
            'reason': 'Failed to create chart'
        }
    
    # Analyze with vision
    result = analyze_chart_with_vision(ticker, chart_path)
    
    if not result['success']:
        logger.error(f"{ticker}: Vision analysis failed: {result['error']}")
        return {
            'vision_approved': False,
            'adjusted_confidence': confidence,
            'analysis': None,
            'cost': 0,
            'reason': f"Vision analysis failed: {result['error']}"
        }
    
    analysis = result['analysis']
    outlook = analysis.get('outlook', 'neutral')
    vision_confidence = analysis.get('confidence', 'medium')
    
    # Adjust confidence based on vision analysis
    adjusted_confidence = confidence
    vision_approved = False
    reason = ""
    
    if outlook == 'bullish' and vision_confidence in ['high', 'medium']:
        # Vision confirms bullish outlook
        if vision_confidence == 'high':
            adjusted_confidence = min(confidence * 1.15, 1.0)  # Boost by 15%
            reason = "Vision analysis STRONGLY confirms bullish setup"
        else:
            adjusted_confidence = min(confidence * 1.08, 1.0)  # Boost by 8%
            reason = "Vision analysis confirms bullish setup"
        vision_approved = True
        
    elif outlook == 'bearish':
        # Vision sees bearish signals
        adjusted_confidence = confidence * 0.6  # Reduce by 40%
        reason = "Vision analysis shows BEARISH signals - reducing confidence"
        vision_approved = False
        
    elif outlook == 'neutral':
        # Vision is neutral
        adjusted_confidence = confidence * 0.9  # Slight reduction
        reason = "Vision analysis is NEUTRAL - slight confidence reduction"
        vision_approved = False
    
    else:
        # Unknown outlook
        reason = f"Vision analysis unclear (outlook: {outlook})"
        vision_approved = False
    
    logger.info(f"{ticker}: Vision check complete - {reason}")
    logger.info(f"{ticker}: Confidence: {confidence:.2f} → {adjusted_confidence:.2f}")
    
    return {
        'vision_approved': vision_approved,
        'adjusted_confidence': adjusted_confidence,
        'analysis': analysis,
        'cost': result['cost'],
        'cache_savings': result.get('cache_savings', 0),
        'savings_pct': result.get('savings_pct', 0),
        'reason': reason
    }
