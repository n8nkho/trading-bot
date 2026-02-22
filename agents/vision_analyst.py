"""
Vision Analyst Agent
Uses FREE local pattern detection for technical analysis
No API costs - pure Python math with numpy/pandas
"""

import json
import logging
from datetime import datetime
from pathlib import Path
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
from scipy.signal import find_peaks

# Setup logging
logger = logging.getLogger(__name__)


def calculate_rsi(prices, period=14):
    """Calculate RSI indicator."""
    if len(prices) < period + 1:
        return np.full(len(prices), 50.0)  # Return neutral RSI if not enough data
    
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


def detect_support_resistance(prices, window=20, tolerance=0.02):
    """
    Detect support and resistance levels using local minima/maxima.
    
    Args:
        prices: Array of prices
        window: Window size for finding peaks
        tolerance: Price tolerance for grouping levels (2% default)
        
    Returns:
        dict: {'support': [levels], 'resistance': [levels]}
    """
    if len(prices) < window:
        return {'support': [], 'resistance': []}
    
    # Find local minima (support) and maxima (resistance)
    support_indices, _ = find_peaks(-prices, distance=window)
    resistance_indices, _ = find_peaks(prices, distance=window)
    
    support_levels = prices[support_indices]
    resistance_levels = prices[resistance_indices]
    
    # Group nearby levels (within tolerance)
    def group_levels(levels, tolerance):
        if len(levels) == 0:
            return []
        
        sorted_levels = np.sort(levels)
        grouped = []
        current_group = [sorted_levels[0]]
        
        for level in sorted_levels[1:]:
            if level <= current_group[-1] * (1 + tolerance):
                current_group.append(level)
            else:
                # Average the group and count touches
                if len(current_group) >= 3:  # Need 3+ touches to be significant
                    grouped.append(np.mean(current_group))
                current_group = [level]
        
        # Don't forget the last group
        if len(current_group) >= 3:
            grouped.append(np.mean(current_group))
        
        return grouped
    
    support = group_levels(support_levels, tolerance)
    resistance = group_levels(resistance_levels, tolerance)
    
    return {
        'support': sorted(support),
        'resistance': sorted(resistance)
    }


def detect_trend(prices, dates=None):
    """
    Detect trend using linear regression.
    
    Args:
        prices: Array of prices
        dates: Optional array of dates (for x-axis)
        
    Returns:
        dict: {
            'direction': 'uptrend'/'downtrend'/'sideways',
            'strength': 'strong'/'moderate'/'weak',
            'slope': float,
            'r_squared': float
        }
    """
    if len(prices) < 10:
        return {
            'direction': 'sideways',
            'strength': 'weak',
            'slope': 0,
            'r_squared': 0
        }
    
    # Use index as x-axis if dates not provided
    x = np.arange(len(prices))
    y = prices
    
    # Linear regression
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
    r_squared = r_value ** 2
    
    # Determine direction based on slope
    slope_pct = (slope * len(prices)) / prices[0] * 100  # Slope as % of starting price
    
    if abs(slope_pct) < 2:
        direction = 'sideways'
    elif slope_pct > 0:
        direction = 'uptrend'
    else:
        direction = 'downtrend'
    
    # Determine strength based on R-squared
    if r_squared > 0.7:
        strength = 'strong'
    elif r_squared > 0.4:
        strength = 'moderate'
    else:
        strength = 'weak'
    
    return {
        'direction': direction,
        'strength': strength,
        'slope': slope,
        'slope_pct': slope_pct,
        'r_squared': r_squared
    }


def detect_rsi_divergence(prices, rsi, lookback=20):
    """
    Detect bullish/bearish RSI divergence.
    
    Bullish divergence: Price makes lower low, RSI makes higher low
    Bearish divergence: Price makes higher high, RSI makes lower high
    
    Args:
        prices: Array of prices
        rsi: Array of RSI values
        lookback: Number of periods to look back
        
    Returns:
        dict: {
            'bullish_divergence': bool,
            'bearish_divergence': bool,
            'strength': 'strong'/'moderate'/'weak'/None
        }
    """
    if len(prices) < lookback or len(rsi) < lookback:
        return {
            'bullish_divergence': False,
            'bearish_divergence': False,
            'strength': None
        }
    
    # Look at recent data
    recent_prices = prices[-lookback:]
    recent_rsi = rsi[-lookback:]
    
    # Find local minima and maxima
    price_lows_idx, _ = find_peaks(-recent_prices, distance=5)
    price_highs_idx, _ = find_peaks(recent_prices, distance=5)
    rsi_lows_idx, _ = find_peaks(-recent_rsi, distance=5)
    rsi_highs_idx, _ = find_peaks(recent_rsi, distance=5)
    
    bullish_divergence = False
    bearish_divergence = False
    strength = None
    
    # Check for bullish divergence (price lower low, RSI higher low)
    if len(price_lows_idx) >= 2 and len(rsi_lows_idx) >= 2:
        price_low1, price_low2 = recent_prices[price_lows_idx[-2]], recent_prices[price_lows_idx[-1]]
        rsi_low1, rsi_low2 = recent_rsi[rsi_lows_idx[-2]], recent_rsi[rsi_lows_idx[-1]]
        
        if price_low2 < price_low1 and rsi_low2 > rsi_low1:
            bullish_divergence = True
            # Strength based on magnitude of divergence
            price_diff = abs(price_low2 - price_low1) / price_low1
            rsi_diff = abs(rsi_low2 - rsi_low1)
            if price_diff > 0.05 and rsi_diff > 10:
                strength = 'strong'
            elif price_diff > 0.02 and rsi_diff > 5:
                strength = 'moderate'
            else:
                strength = 'weak'
    
    # Check for bearish divergence (price higher high, RSI lower high)
    if len(price_highs_idx) >= 2 and len(rsi_highs_idx) >= 2:
        price_high1, price_high2 = recent_prices[price_highs_idx[-2]], recent_prices[price_highs_idx[-1]]
        rsi_high1, rsi_high2 = recent_rsi[rsi_highs_idx[-2]], recent_rsi[rsi_highs_idx[-1]]
        
        if price_high2 > price_high1 and rsi_high2 < rsi_high1:
            bearish_divergence = True
            # Strength based on magnitude of divergence
            price_diff = abs(price_high2 - price_high1) / price_high1
            rsi_diff = abs(rsi_high2 - rsi_high1)
            if price_diff > 0.05 and rsi_diff > 10:
                strength = 'strong'
            elif price_diff > 0.02 and rsi_diff > 5:
                strength = 'moderate'
            else:
                strength = 'weak'
    
    return {
        'bullish_divergence': bullish_divergence,
        'bearish_divergence': bearish_divergence,
        'strength': strength
    }


def detect_volume_spikes(volumes, threshold=2.0):
    """
    Detect volume spikes (volume > threshold * average).
    
    Args:
        volumes: Array of volume data
        threshold: Multiplier for average volume (2.0 = 200% of average)
        
    Returns:
        dict: {
            'has_spike': bool,
            'recent_spike': bool (in last 5 periods),
            'spike_ratio': float (current volume / average)
        }
    """
    if len(volumes) < 20:
        return {
            'has_spike': False,
            'recent_spike': False,
            'spike_ratio': 1.0
        }
    
    avg_volume = np.mean(volumes[:-5])  # Average excluding last 5 periods
    recent_volumes = volumes[-5:]
    current_volume = volumes[-1]
    
    spike_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
    has_spike = spike_ratio > threshold
    recent_spike = any(v / avg_volume > threshold for v in recent_volumes)
    
    return {
        'has_spike': has_spike,
        'recent_spike': recent_spike,
        'spike_ratio': spike_ratio,
        'avg_volume': avg_volume
    }


def analyze_chart_patterns(ticker, price_data=None, period='3mo', interval='1d'):
    """
    Analyze chart patterns using FREE local detection (no API calls).
    
    Args:
        ticker: Stock symbol
        price_data: Optional pre-loaded DataFrame (if None, will fetch)
        period: Historical period to analyze
        interval: Data interval
        
    Returns:
        dict: {
            'success': bool,
            'patterns': {
                'support_levels': [prices],
                'resistance_levels': [prices],
                'trend': dict,
                'rsi_divergence': dict,
                'volume_spike': dict,
                'current_price': float,
                'current_rsi': float
            },
            'error': str or None
        }
    """
    try:
        logger.info(f"{ticker}: Analyzing chart patterns (FREE local detection)")
        
        # Fetch data if not provided
        if price_data is None:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)
            
            if df.empty:
                logger.error(f"{ticker}: No data available")
                return {
                    'success': False,
                    'patterns': None,
                    'error': 'No data available'
                }
        else:
            df = price_data
        
        # Extract arrays
        prices = df['Close'].values
        volumes = df['Volume'].values
        
        # Calculate RSI
        rsi = calculate_rsi(prices)
        
        # Detect patterns
        support_resistance = detect_support_resistance(prices)
        trend = detect_trend(prices)
        divergence = detect_rsi_divergence(prices, rsi)
        volume_spike = detect_volume_spikes(volumes)
        
        # Current values
        current_price = prices[-1]
        current_rsi = rsi[-1]
        
        patterns = {
            'support_levels': support_resistance['support'],
            'resistance_levels': support_resistance['resistance'],
            'trend': trend,
            'rsi_divergence': divergence,
            'volume_spike': volume_spike,
            'current_price': current_price,
            'current_rsi': current_rsi,
            'price_change_pct': ((prices[-1] - prices[0]) / prices[0] * 100) if len(prices) > 0 else 0
        }
        
        logger.info(f"{ticker}: Pattern detection complete - Trend: {trend['direction']}, RSI: {current_rsi:.1f}")
        
        return {
            'success': True,
            'patterns': patterns,
            'error': None
        }
        
    except Exception as e:
        logger.error(f"{ticker}: Error analyzing patterns: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'patterns': None,
            'error': f"{type(e).__name__}: {str(e)}"
        }


def pattern_to_signal(patterns):
    """
    Convert detected patterns to trading signal.
    
    Logic:
    - Price near support + RSI < 30 = STRONG_BUY
    - Price near support + RSI < 40 + bullish divergence = BUY
    - Price near resistance + RSI > 70 = AVOID
    - Bullish divergence alone = BUY
    - Strong uptrend + volume spike = BUY
    
    Args:
        patterns: Dict from analyze_chart_patterns()
        
    Returns:
        dict: {
            'signal': 'STRONG_BUY'/'BUY'/'HOLD'/'AVOID',
            'confidence': float (0-1),
            'reasoning': [list of reasons],
            'entry_price': float or None,
            'stop_loss': float or None
        }
    """
    if not patterns:
        return {
            'signal': 'HOLD',
            'confidence': 0.0,
            'reasoning': ['No pattern data available'],
            'entry_price': None,
            'stop_loss': None
        }
    
    current_price = patterns['current_price']
    current_rsi = patterns['current_rsi']
    support_levels = patterns['support_levels']
    resistance_levels = patterns['resistance_levels']
    trend = patterns['trend']
    divergence = patterns['rsi_divergence']
    volume_spike = patterns['volume_spike']
    
    signal = 'HOLD'
    confidence = 0.5
    reasoning = []
    entry_price = None
    stop_loss = None
    
    # Check if price is near support (within 3%)
    near_support = False
    closest_support = None
    if support_levels:
        closest_support = min(support_levels, key=lambda x: abs(x - current_price))
        if abs(current_price - closest_support) / current_price < 0.03:
            near_support = True
    
    # Check if price is near resistance (within 3%)
    near_resistance = False
    closest_resistance = None
    if resistance_levels:
        closest_resistance = min(resistance_levels, key=lambda x: abs(x - current_price))
        if abs(current_price - closest_resistance) / current_price < 0.03:
            near_resistance = True
    
    # AVOID signals (bearish)
    if near_resistance and current_rsi > 70:
        signal = 'AVOID'
        confidence = 0.8
        reasoning.append(f"Price near resistance (${closest_resistance:.2f}) + RSI overbought ({current_rsi:.1f})")
        return {
            'signal': signal,
            'confidence': confidence,
            'reasoning': reasoning,
            'entry_price': None,
            'stop_loss': None
        }
    
    if divergence['bearish_divergence']:
        signal = 'AVOID'
        confidence = 0.7 if divergence['strength'] == 'strong' else 0.6
        reasoning.append(f"Bearish RSI divergence detected ({divergence['strength']})")
        return {
            'signal': signal,
            'confidence': confidence,
            'reasoning': reasoning,
            'entry_price': None,
            'stop_loss': None
        }
    
    # STRONG_BUY signals (very bullish)
    if near_support and current_rsi < 30:
        signal = 'STRONG_BUY'
        confidence = 0.85
        reasoning.append(f"Price near support (${closest_support:.2f}) + RSI oversold ({current_rsi:.1f})")
        entry_price = current_price
        stop_loss = closest_support * 0.97  # 3% below support
    
    elif divergence['bullish_divergence'] and divergence['strength'] == 'strong' and current_rsi < 40:
        signal = 'STRONG_BUY'
        confidence = 0.8
        reasoning.append(f"Strong bullish RSI divergence + RSI < 40 ({current_rsi:.1f})")
        entry_price = current_price
        stop_loss = current_price * 0.95  # 5% stop loss
    
    # BUY signals (bullish)
    elif near_support and current_rsi < 40:
        signal = 'BUY'
        confidence = 0.75
        reasoning.append(f"Price near support (${closest_support:.2f}) + RSI low ({current_rsi:.1f})")
        entry_price = current_price
        stop_loss = closest_support * 0.97
    
    elif divergence['bullish_divergence']:
        signal = 'BUY'
        confidence = 0.7 if divergence['strength'] in ['strong', 'moderate'] else 0.6
        reasoning.append(f"Bullish RSI divergence detected ({divergence['strength']})")
        entry_price = current_price
        stop_loss = current_price * 0.95
    
    elif trend['direction'] == 'uptrend' and trend['strength'] in ['strong', 'moderate'] and volume_spike['recent_spike']:
        signal = 'BUY'
        confidence = 0.7
        reasoning.append(f"{trend['strength']} uptrend + volume spike ({volume_spike['spike_ratio']:.1f}x avg)")
        entry_price = current_price
        stop_loss = current_price * 0.93  # 7% stop loss for momentum plays
    
    elif current_rsi < 30 and trend['direction'] != 'downtrend':
        signal = 'BUY'
        confidence = 0.65
        reasoning.append(f"RSI oversold ({current_rsi:.1f}) + not in downtrend")
        entry_price = current_price
        stop_loss = current_price * 0.95
    
    # Add additional context
    if trend['direction'] != 'sideways':
        reasoning.append(f"Trend: {trend['strength']} {trend['direction']} (slope: {trend['slope_pct']:.1f}%)")
    
    if volume_spike['has_spike']:
        reasoning.append(f"Current volume spike: {volume_spike['spike_ratio']:.1f}x average")
    
    return {
        'signal': signal,
        'confidence': confidence,
        'reasoning': reasoning,
        'entry_price': entry_price,
        'stop_loss': stop_loss
    }




def quick_vision_check(ticker, confidence):
    """
    Quick FREE pattern check for high-confidence candidates.
    Uses local pattern detection (no API costs).
    
    Args:
        ticker: Stock symbol
        confidence: Current confidence score
        
    Returns:
        dict: {
            'vision_approved': bool,
            'adjusted_confidence': float,
            'patterns': dict or None,
            'signal': dict,
            'reason': str
        }
    """
    logger.info(f"{ticker}: Running quick pattern check (confidence: {confidence:.2f})")
    
    # Analyze patterns
    result = analyze_chart_patterns(ticker, period='3mo', interval='1d')
    
    if not result['success']:
        logger.error(f"{ticker}: Pattern analysis failed: {result['error']}")
        return {
            'vision_approved': False,
            'adjusted_confidence': confidence,
            'patterns': None,
            'signal': None,
            'reason': f"Pattern analysis failed: {result['error']}"
        }
    
    patterns = result['patterns']
    
    # Convert patterns to signal
    signal = pattern_to_signal(patterns)
    
    # Adjust confidence based on pattern analysis
    adjusted_confidence = confidence
    vision_approved = False
    reason = ""
    
    if signal['signal'] == 'STRONG_BUY':
        # Strong buy signal
        adjusted_confidence = min(confidence * 1.2, 1.0)  # Boost by 20%
        reason = f"STRONG_BUY signal: {', '.join(signal['reasoning'])}"
        vision_approved = True
        
    elif signal['signal'] == 'BUY':
        # Buy signal
        adjusted_confidence = min(confidence * 1.1, 1.0)  # Boost by 10%
        reason = f"BUY signal: {', '.join(signal['reasoning'])}"
        vision_approved = True
        
    elif signal['signal'] == 'AVOID':
        # Avoid signal
        adjusted_confidence = confidence * 0.5  # Reduce by 50%
        reason = f"AVOID signal: {', '.join(signal['reasoning'])}"
        vision_approved = False
        
    else:
        # Hold signal
        adjusted_confidence = confidence * 0.95  # Slight reduction
        reason = f"HOLD signal: {', '.join(signal['reasoning'])}"
        vision_approved = False
    
    logger.info(f"{ticker}: Pattern check complete - {reason}")
    logger.info(f"{ticker}: Confidence: {confidence:.2f} → {adjusted_confidence:.2f}")
    
    return {
        'vision_approved': vision_approved,
        'adjusted_confidence': adjusted_confidence,
        'patterns': patterns,
        'signal': signal,
        'reason': reason
    }
