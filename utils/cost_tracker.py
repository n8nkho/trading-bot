"""
API Cost Tracker - Monitor costs and savings from prompt caching
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# Pricing per 1M tokens (as of Feb 2026)
PRICING = {
    "claude-3-5-sonnet-20241022": {
        "input": 3.00,           # $3 per 1M input tokens
        "cached_input": 0.30,    # $0.30 per 1M cached tokens (90% discount)
        "output": 15.00          # $15 per 1M output tokens
    },
    "claude-3-opus-20240229": {
        "input": 15.00,
        "cached_input": 1.50,
        "output": 75.00
    },
    "claude-3-sonnet-20240229": {
        "input": 3.00,
        "cached_input": 0.30,
        "output": 15.00
    },
    "claude-3-haiku-20240307": {
        "input": 0.25,
        "cached_input": 0.03,
        "output": 1.25
    }
}

DATA_DIR = Path("data")
COST_LOG_FILE = DATA_DIR / "api_costs.jsonl"


def ensure_data_dir():
    """Ensure data directory exists"""
    DATA_DIR.mkdir(exist_ok=True)


def track_api_call(model, input_tokens, cached_tokens, output_tokens):
    """
    Track an API call and calculate costs with/without caching.
    
    Args:
        model: Model name (e.g., "claude-3-5-sonnet-20241022")
        input_tokens: Total input tokens
        cached_tokens: Number of cached input tokens
        output_tokens: Output tokens generated
    
    Returns:
        dict: Cost breakdown with savings
    """
    ensure_data_dir()
    
    # Get pricing for model
    if model not in PRICING:
        print(f"Warning: Unknown model {model}, using Sonnet pricing")
        model = "claude-3-5-sonnet-20241022"
    
    pricing = PRICING[model]
    
    # Calculate tokens
    uncached_tokens = input_tokens - cached_tokens
    
    # Cost WITH caching
    cost_with_cache = (
        (uncached_tokens / 1_000_000) * pricing["input"] +
        (cached_tokens / 1_000_000) * pricing["cached_input"] +
        (output_tokens / 1_000_000) * pricing["output"]
    )
    
    # Cost WITHOUT caching (all input tokens at full price)
    cost_without_cache = (
        (input_tokens / 1_000_000) * pricing["input"] +
        (output_tokens / 1_000_000) * pricing["output"]
    )
    
    # Calculate savings
    savings = cost_without_cache - cost_with_cache
    savings_pct = (savings / cost_without_cache * 100) if cost_without_cache > 0 else 0
    
    # Create log entry
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "cost_with_cache": round(cost_with_cache, 6),
        "cost_without_cache": round(cost_without_cache, 6),
        "savings": round(savings, 6),
        "savings_pct": round(savings_pct, 1)
    }
    
    # Append to log file
    with open(COST_LOG_FILE, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')
    
    return log_entry


def load_api_calls(start_date=None, end_date=None):
    """
    Load API calls from log file within date range.
    
    Args:
        start_date: datetime object for start (inclusive)
        end_date: datetime object for end (inclusive)
    
    Returns:
        list: API call records
    """
    if not COST_LOG_FILE.exists():
        return []
    
    calls = []
    with open(COST_LOG_FILE, 'r') as f:
        for line in f:
            if line.strip():
                call = json.loads(line)
                call_time = datetime.fromisoformat(call["timestamp"])
                
                # Filter by date range if provided
                if start_date and call_time < start_date:
                    continue
                if end_date and call_time > end_date:
                    continue
                
                calls.append(call)
    
    return calls


def get_daily_savings():
    """
    Get today's API cost savings from caching.
    
    Returns:
        dict: {
            "total_cost": float,
            "savings": float,
            "savings_percentage": float,
            "call_count": int,
            "cache_hit_rate": float
        }
    """
    # Get today's calls
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    calls = load_api_calls(start_date=today_start, end_date=today_end)
    
    if not calls:
        return {
            "total_cost": 0.0,
            "savings": 0.0,
            "savings_percentage": 0.0,
            "call_count": 0,
            "cache_hit_rate": 0.0
        }
    
    # Sum up costs and savings
    total_cost = sum(call["cost_with_cache"] for call in calls)
    total_savings = sum(call["savings"] for call in calls)
    total_without_cache = total_cost + total_savings
    
    savings_pct = (total_savings / total_without_cache * 100) if total_without_cache > 0 else 0
    
    # Calculate cache hit rate
    total_input_tokens = sum(call["input_tokens"] for call in calls)
    total_cached_tokens = sum(call["cached_tokens"] for call in calls)
    cache_hit_rate = (total_cached_tokens / total_input_tokens * 100) if total_input_tokens > 0 else 0
    
    return {
        "total_cost": round(total_cost, 4),
        "savings": round(total_savings, 4),
        "savings_percentage": round(savings_pct, 1),
        "call_count": len(calls),
        "cache_hit_rate": round(cache_hit_rate, 1)
    }


def get_monthly_projection():
    """
    Project monthly costs based on daily average.
    
    Returns:
        dict: {
            "daily_avg_with_cache": float,
            "daily_avg_without_cache": float,
            "monthly_with_cache": float,
            "monthly_without_cache": float,
            "monthly_savings": float,
            "days_analyzed": int
        }
    """
    # Get last 30 days of data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    calls = load_api_calls(start_date=start_date, end_date=end_date)
    
    if not calls:
        return {
            "daily_avg_with_cache": 0.0,
            "daily_avg_without_cache": 0.0,
            "monthly_with_cache": 0.0,
            "monthly_without_cache": 0.0,
            "monthly_savings": 0.0,
            "days_analyzed": 0
        }
    
    # Calculate totals
    total_cost_with_cache = sum(call["cost_with_cache"] for call in calls)
    total_cost_without_cache = sum(call["cost_without_cache"] for call in calls)
    
    # Get unique days
    unique_days = len(set(
        datetime.fromisoformat(call["timestamp"]).date()
        for call in calls
    ))
    
    # Calculate daily averages
    daily_avg_with = total_cost_with_cache / unique_days if unique_days > 0 else 0
    daily_avg_without = total_cost_without_cache / unique_days if unique_days > 0 else 0
    
    # Project to 30 days
    monthly_with = daily_avg_with * 30
    monthly_without = daily_avg_without * 30
    monthly_savings = monthly_without - monthly_with
    
    return {
        "daily_avg_with_cache": round(daily_avg_with, 4),
        "daily_avg_without_cache": round(daily_avg_without, 4),
        "monthly_with_cache": round(monthly_with, 2),
        "monthly_without_cache": round(monthly_without, 2),
        "monthly_savings": round(monthly_savings, 2),
        "days_analyzed": unique_days
    }


def get_cost_health_check():
    """
    Generate health check report for API costs.
    
    Returns:
        dict: Health status with alerts
    """
    daily = get_daily_savings()
    monthly = get_monthly_projection()
    
    alerts = []
    
    # Alert if cache hit rate is low
    if daily["cache_hit_rate"] < 50 and daily["call_count"] > 0:
        alerts.append({
            "level": "warning",
            "message": f"Low cache hit rate: {daily['cache_hit_rate']}% (target: >50%)"
        })
    
    # Alert if daily costs are high
    if daily["total_cost"] > 5.0:
        alerts.append({
            "level": "warning",
            "message": f"High daily cost: ${daily['total_cost']:.2f}"
        })
    
    # Alert if projected monthly costs are high
    if monthly["monthly_with_cache"] > 100:
        alerts.append({
            "level": "warning",
            "message": f"Projected monthly cost: ${monthly['monthly_with_cache']:.2f}"
        })
    
    return {
        "status": "warning" if alerts else "healthy",
        "daily": daily,
        "monthly": monthly,
        "alerts": alerts
    }


if __name__ == "__main__":
    # Example usage
    print("API Cost Tracker")
    print("=" * 50)
    
    # Show daily savings
    daily = get_daily_savings()
    print(f"\nToday's Summary:")
    print(f"  API Calls: {daily['call_count']}")
    print(f"  Total Cost: ${daily['total_cost']:.4f}")
    print(f"  Savings: ${daily['savings']:.4f} ({daily['savings_percentage']:.1f}%)")
    print(f"  Cache Hit Rate: {daily['cache_hit_rate']:.1f}%")
    
    # Show monthly projection
    monthly = get_monthly_projection()
    print(f"\nMonthly Projection (based on {monthly['days_analyzed']} days):")
    print(f"  With Cache: ${monthly['monthly_with_cache']:.2f}")
    print(f"  Without Cache: ${monthly['monthly_without_cache']:.2f}")
    print(f"  Savings: ${monthly['monthly_savings']:.2f}")
    
    # Show health check
    health = get_cost_health_check()
    print(f"\nHealth Status: {health['status'].upper()}")
    if health['alerts']:
        print("Alerts:")
        for alert in health['alerts']:
            print(f"  [{alert['level'].upper()}] {alert['message']}")
